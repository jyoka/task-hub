// slack-triage-hotkey: ショートカットキーを押したら slack-triage を起動するだけの常駐プログラム。
// macOS の RegisterEventHotKey を使うので、アクセシビリティや入力監視の権限は要らない。
//   slack-triage-hotkey --key s --mods ctrl,opt --status <file> -- <command> [args...]
import AppKit
import Carbon

func fail(_ msg: String) -> Never {
    FileHandle.standardError.write((msg + "\n").data(using: .utf8)!)
    exit(2)
}

var keyName = "s"
var modNames = "ctrl,opt"
var statusPath = ""
var configPath = ""
var command: [String] = []

var args = Array(CommandLine.arguments.dropFirst())
while !args.isEmpty {
    let a = args.removeFirst()
    switch a {
    case "--key": keyName = args.isEmpty ? "" : args.removeFirst().lowercased()
    case "--mods": modNames = args.isEmpty ? "" : args.removeFirst().lowercased()
    case "--status": statusPath = args.isEmpty ? "" : args.removeFirst()
    case "--config": configPath = args.isEmpty ? "" : args.removeFirst()
    case "--": command = args; args = []
    default: fail("unknown argument: \(a)")
    }
}
if command.isEmpty { fail("usage: slack-triage-hotkey [--key s --mods ctrl,opt | --config FILE] --status FILE -- COMMAND [ARGS...]") }

// --config: JSON の hotkey_key / hotkey_mods があればそちらを使う（slack-triage key で変えられる）
if !configPath.isEmpty,
   let data = FileManager.default.contents(atPath: configPath),
   let obj = try? JSONSerialization.jsonObject(with: data) as? [String: Any] {
    if let k = obj["hotkey_key"] as? String, !k.isEmpty { keyName = k.lowercased() }
    if let m = obj["hotkey_mods"] as? String, !m.isEmpty { modNames = m.lowercased() }
}

// 英字キー（US 配列の位置）
let keyCodes: [String: Int] = [
    "a": kVK_ANSI_A, "b": kVK_ANSI_B, "c": kVK_ANSI_C, "d": kVK_ANSI_D, "e": kVK_ANSI_E, "f": kVK_ANSI_F,
    "g": kVK_ANSI_G, "h": kVK_ANSI_H, "i": kVK_ANSI_I, "j": kVK_ANSI_J, "k": kVK_ANSI_K, "l": kVK_ANSI_L,
    "m": kVK_ANSI_M, "n": kVK_ANSI_N, "o": kVK_ANSI_O, "p": kVK_ANSI_P, "q": kVK_ANSI_Q, "r": kVK_ANSI_R,
    "s": kVK_ANSI_S, "t": kVK_ANSI_T, "u": kVK_ANSI_U, "v": kVK_ANSI_V, "w": kVK_ANSI_W, "x": kVK_ANSI_X,
    "y": kVK_ANSI_Y, "z": kVK_ANSI_Z,
]
guard let keyCode = keyCodes[keyName] else { fail("unsupported key: \(keyName) (a-z only)") }

var mods: UInt32 = 0
for m in modNames.split(separator: ",") {
    switch m.trimmingCharacters(in: .whitespaces) {
    case "ctrl", "control": mods |= UInt32(controlKey)
    case "opt", "option", "alt": mods |= UInt32(optionKey)
    case "cmd", "command": mods |= UInt32(cmdKey)
    case "shift": mods |= UInt32(shiftKey)
    default: fail("unsupported modifier: \(m)")
    }
}
if mods == 0 { fail("at least one modifier is required") }

func writeStatus(_ s: String) {
    guard !statusPath.isEmpty else { return }
    let url = URL(fileURLWithPath: statusPath)
    try? FileManager.default.createDirectory(at: url.deletingLastPathComponent(), withIntermediateDirectories: true)
    try? (s + "\n").write(to: url, atomically: true, encoding: .utf8)
}

var lastLaunch = Date.distantPast

func launch() {
    // 連打で何個も起動しないように（本体側でも二重起動は防いでいる）
    if Date().timeIntervalSince(lastLaunch) < 1.0 { return }
    lastLaunch = Date()
    let p = Process()
    p.executableURL = URL(fileURLWithPath: command[0])
    p.arguments = Array(command.dropFirst())
    var env = ProcessInfo.processInfo.environment
    env["LANG"] = "ja_JP.UTF-8"
    env["LC_ALL"] = "ja_JP.UTF-8"
    p.environment = env
    p.standardInput = FileHandle.nullDevice
    do { try p.run() } catch {
        FileHandle.standardError.write("launch failed: \(error)\n".data(using: .utf8)!)
    }
}

let app = NSApplication.shared
app.setActivationPolicy(.prohibited)  // Dock にもメニューバーにも出さない

var handlerRef: EventHandlerRef?
var spec = EventTypeSpec(eventClass: OSType(kEventClassKeyboard), eventKind: UInt32(kEventHotKeyPressed))
InstallEventHandler(GetApplicationEventTarget(), { _, _, _ in
    launch()
    return noErr
}, 1, &spec, nil, &handlerRef)

var hotKeyRef: EventHotKeyRef?
let hotKeyID = EventHotKeyID(signature: OSType(0x534C_5452), id: 1)  // 'SLTR'
let err = RegisterEventHotKey(UInt32(keyCode), mods, hotKeyID, GetApplicationEventTarget(), 0, &hotKeyRef)
if err != noErr {
    // -9878: ほかのアプリが同じキーを使っている
    writeStatus(err == OSStatus(eventHotKeyExistsErr) ? "conflict" : "error \(err)")
    FileHandle.standardError.write("RegisterEventHotKey failed: \(err)\n".data(using: .utf8)!)
    exit(0)  // launchd（KeepAlive: SuccessfulExit=false）に再起動を繰り返させない
}
writeStatus("ok \(modNames)+\(keyName)")

// ログアウトや launchctl bootout で終わるまで待つ
signal(SIGTERM) { _ in exit(0) }
app.run()
