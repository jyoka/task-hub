// Builds, then zips the VSIX (no vsce): the manifest files VS Code and Kiro read, and extension/ with what runs.
// Writes task-hub-board-<version>.vsix next to package.json. Needs `zip` (macOS has /usr/bin/zip).
import { execFileSync } from 'node:child_process'
import { cpSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'

import { ROOT, build } from './build.mjs'

const FILES = ['package.json', 'out', 'media']

const xml = s => String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const manifest = p => `<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011">
  <Metadata>
    <Identity Language="en-US" Id="${xml(p.name)}" Version="${xml(p.version)}" Publisher="${xml(p.publisher)}" />
    <DisplayName>${xml(p.displayName)}</DisplayName>
    <Description xml:space="preserve">${xml(p.description)}</Description>
    <Properties><Property Id="Microsoft.VisualStudio.Code.Engine" Value="${xml(p.engines.vscode)}" /></Properties>
  </Metadata>
  <Installation><InstallationTarget Id="Microsoft.VisualStudio.Code"/></Installation>
  <Dependencies/>
  <Assets><Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" /></Assets>
</PackageManifest>
`

const CONTENT_TYPES = `<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">\
<Default Extension=".json" ContentType="application/json"/>\
<Default Extension=".js" ContentType="application/javascript"/>\
<Default Extension=".svg" ContentType="image/svg+xml"/>\
<Default Extension=".vsixmanifest" ContentType="text/xml"/></Types>
`

export const pack = () => {
  const p = JSON.parse(readFileSync(join(ROOT, 'package.json'), 'utf8'))
  build()
  const stage = mkdtempSync(join(tmpdir(), 'task-hub-board-'))
  try {
    for (const f of FILES) cpSync(join(ROOT, f), join(stage, 'extension', f), { recursive: true })
    writeFileSync(join(stage, 'extension.vsixmanifest'), manifest(p))
    writeFileSync(join(stage, '[Content_Types].xml'), CONTENT_TYPES)
    const vsix = join(ROOT, `${p.name}-${p.version}.vsix`)
    rmSync(vsix, { force: true })
    execFileSync('zip', ['-q', '-X', '-r', vsix, '.'], { cwd: stage })
    return vsix
  } finally {
    rmSync(stage, { recursive: true, force: true })
  }
}

console.log(`wrote ${pack()}`)
