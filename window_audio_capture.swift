import AVFoundation
import CoreMedia
import Foundation
import ScreenCaptureKit

struct WindowInfo: Codable {
    let id: UInt32
    let title: String
    let app: String
    let pid: Int32
}

struct AppInfo: Codable {
    let app: String
    let pid: Int32
    let bundleIdentifier: String
}

func writeLine(_ value: String) {
    FileHandle.standardError.write((value + "\n").data(using: .utf8)!)
}

func shareableContent() async throws -> SCShareableContent {
    try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
}

func listWindows() async throws {
    let content = try await shareableContent()
    let windows = content.windows.compactMap { window -> WindowInfo? in
        guard let app = window.owningApplication else {
            return nil
        }
        let title = (window.title?.isEmpty == false) ? window.title! : "(Untitled)"
        return WindowInfo(
            id: window.windowID,
            title: title,
            app: app.applicationName,
            pid: app.processID
        )
    }

    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    let data = try encoder.encode(windows)
    FileHandle.standardOutput.write(data)
}

func listApps() async throws {
    let content = try await shareableContent()
    let apps = content.applications
        .filter { !$0.applicationName.isEmpty }
        .map {
            AppInfo(
                app: $0.applicationName,
                pid: $0.processID,
                bundleIdentifier: $0.bundleIdentifier
            )
        }
        .sorted { left, right in
            left.app.localizedCaseInsensitiveCompare(right.app) == .orderedAscending
        }

    let encoder = JSONEncoder()
    encoder.outputFormatting = [.prettyPrinted, .sortedKeys]
    let data = try encoder.encode(apps)
    FileHandle.standardOutput.write(data)
}

final class AudioPipeOutput: NSObject, SCStreamOutput, SCStreamDelegate {
    private let outputFormat: AVAudioFormat
    private var converters: [String: AVAudioConverter] = [:]

    override init() {
        outputFormat = AVAudioFormat(
            commonFormat: .pcmFormatInt16,
            sampleRate: 16_000,
            channels: 1,
            interleaved: true
        )!
        super.init()
    }

    func stream(
        _ stream: SCStream,
        didStopWithError error: Error
    ) {
        writeLine("capture stopped: \(error.localizedDescription)")
        Foundation.exit(2)
    }

    func stream(
        _ stream: SCStream,
        didOutputSampleBuffer sampleBuffer: CMSampleBuffer,
        of outputType: SCStreamOutputType
    ) {
        guard outputType == .audio, sampleBuffer.isValid else {
            return
        }

        do {
            guard let inputBuffer = try makePCMBuffer(from: sampleBuffer) else {
                return
            }
            guard let converted = convert(inputBuffer) else {
                return
            }
            writeInt16PCM(converted)
        } catch {
            writeLine("audio buffer error: \(error.localizedDescription)")
        }
    }

    private func makePCMBuffer(from sampleBuffer: CMSampleBuffer) throws -> AVAudioPCMBuffer? {
        guard let formatDescription = CMSampleBufferGetFormatDescription(sampleBuffer),
              let streamDescription = CMAudioFormatDescriptionGetStreamBasicDescription(formatDescription)
        else {
            return nil
        }

        guard let inputFormat = AVAudioFormat(streamDescription: streamDescription) else {
            return nil
        }
        let frameCount = AVAudioFrameCount(CMSampleBufferGetNumSamples(sampleBuffer))
        guard let pcmBuffer = AVAudioPCMBuffer(pcmFormat: inputFormat, frameCapacity: frameCount) else {
            return nil
        }
        pcmBuffer.frameLength = frameCount

        let status = CMSampleBufferCopyPCMDataIntoAudioBufferList(
            sampleBuffer,
            at: 0,
            frameCount: Int32(frameCount),
            into: pcmBuffer.mutableAudioBufferList
        )

        if status != noErr {
            throw NSError(
                domain: NSOSStatusErrorDomain,
                code: Int(status),
                userInfo: [NSLocalizedDescriptionKey: "CMSampleBufferCopyPCMDataIntoAudioBufferList failed: \(status)"]
            )
        }

        return pcmBuffer
    }

    private func convert(_ inputBuffer: AVAudioPCMBuffer) -> AVAudioPCMBuffer? {
        if inputBuffer.format == outputFormat {
            return inputBuffer
        }

        let key = "\(inputBuffer.format.sampleRate)-\(inputBuffer.format.channelCount)-\(inputBuffer.format.commonFormat.rawValue)-\(inputBuffer.format.isInterleaved)"
        let converter = converters[key] ?? AVAudioConverter(from: inputBuffer.format, to: outputFormat)
        guard let converter else {
            return nil
        }
        converters[key] = converter

        let ratio = outputFormat.sampleRate / inputBuffer.format.sampleRate
        let capacity = max(1, AVAudioFrameCount(Double(inputBuffer.frameLength) * ratio) + 8)
        guard let outputBuffer = AVAudioPCMBuffer(pcmFormat: outputFormat, frameCapacity: capacity) else {
            return nil
        }

        var didProvideInput = false
        var conversionError: NSError?
        converter.convert(to: outputBuffer, error: &conversionError) { _, outStatus in
            if didProvideInput {
                outStatus.pointee = .noDataNow
                return nil
            }
            didProvideInput = true
            outStatus.pointee = .haveData
            return inputBuffer
        }

        if let conversionError {
            writeLine("audio conversion error: \(conversionError.localizedDescription)")
            return nil
        }

        return outputBuffer
    }

    private func writeInt16PCM(_ buffer: AVAudioPCMBuffer) {
        guard let channelData = buffer.int16ChannelData else {
            return
        }

        let frameLength = Int(buffer.frameLength)
        guard frameLength > 0 else {
            return
        }

        let bytes = UnsafeRawBufferPointer(
            start: channelData[0],
            count: frameLength * MemoryLayout<Int16>.size
        )
        FileHandle.standardOutput.write(Data(bytes))
    }
}

func makeFilter(content: SCShareableContent, windowID: UInt32) throws -> SCContentFilter {
    guard let window = content.windows.first(where: { $0.windowID == windowID }) else {
        throw NSError(
            domain: "GemTranslateWindowAudio",
            code: 1,
            userInfo: [NSLocalizedDescriptionKey: "Window \(windowID) was not found"]
        )
    }
    return SCContentFilter(desktopIndependentWindow: window)
}

func makeFilter(content: SCShareableContent, processID: Int32) throws -> SCContentFilter {
    guard let display = content.displays.first else {
        throw NSError(
            domain: "GemTranslateWindowAudio",
            code: 2,
            userInfo: [NSLocalizedDescriptionKey: "No display was found"]
        )
    }
    guard let application = content.applications.first(where: { $0.processID == processID }) else {
        throw NSError(
            domain: "GemTranslateWindowAudio",
            code: 3,
            userInfo: [NSLocalizedDescriptionKey: "Application pid \(processID) was not found"]
        )
    }
    return SCContentFilter(display: display, including: [application], exceptingWindows: [])
}

func captureWindow(windowID: UInt32) async throws {
    let content = try await shareableContent()
    let filter = try makeFilter(content: content, windowID: windowID)
    try await capture(filter: filter, label: "window \(windowID)")
}

func captureApp(processID: Int32) async throws {
    let content = try await shareableContent()
    let filter = try makeFilter(content: content, processID: processID)
    try await capture(filter: filter, label: "app pid \(processID)")
}

func capture(filter: SCContentFilter, label: String) async throws {
    let configuration = SCStreamConfiguration()
    configuration.width = 2
    configuration.height = 2
    configuration.minimumFrameInterval = CMTime(value: 1, timescale: 1)
    configuration.queueDepth = 3
    configuration.capturesAudio = true
    configuration.sampleRate = 16_000
    configuration.channelCount = 1

    let output = AudioPipeOutput()
    let stream = SCStream(filter: filter, configuration: configuration, delegate: output)
    try stream.addStreamOutput(output, type: .audio, sampleHandlerQueue: DispatchQueue(label: "GemTranslate.WindowAudio"))
    try await stream.startCapture()
    writeLine("capturing \(label)")
    while true {
        try await Task.sleep(nanoseconds: 1_000_000_000)
    }
}

@main
struct WindowAudioCapture {
    static func main() async {
        do {
            let args = CommandLine.arguments
            if args.count == 2, args[1] == "list" {
                try await listWindows()
                return
            }
            if args.count == 2, args[1] == "list-apps" {
                try await listApps()
                return
            }
            if args.count == 3, args[1] == "capture-window", let id = UInt32(args[2]) {
                try await captureWindow(windowID: id)
                return
            }
            if args.count == 3, args[1] == "capture-app", let pid = Int32(args[2]) {
                try await captureApp(processID: pid)
                return
            }

            writeLine("usage: window_audio_capture list | list-apps | capture-window <windowID> | capture-app <pid>")
            Foundation.exit(64)
        } catch {
            writeLine(error.localizedDescription)
            Foundation.exit(1)
        }
    }
}
