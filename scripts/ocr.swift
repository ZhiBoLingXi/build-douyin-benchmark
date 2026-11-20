// Read visible subtitles and product copy locally on macOS. Output one JSON record per sampled time.
import Foundation
import AVFoundation
import Vision
let url = URL(fileURLWithPath: CommandLine.arguments[1])
let asset = AVURLAsset(url: url)
let gen = AVAssetImageGenerator(asset: asset)
gen.appliesPreferredTrackTransform = true
gen.maximumSize = CGSize(width: 1280, height: 1280)
gen.requestedTimeToleranceBefore = CMTime(seconds: 0.06, preferredTimescale: 600)
gen.requestedTimeToleranceAfter = gen.requestedTimeToleranceBefore
let duration = CMTimeGetSeconds(asset.duration)
guard duration.isFinite, duration > 0 else { exit(1) }
for t in stride(from: 0.18, to: duration, by: 0.5) {
    autoreleasepool {
        guard let cg = try? gen.copyCGImage(at: CMTime(seconds: t, preferredTimescale: 600), actualTime: nil) else { return }
        let req = VNRecognizeTextRequest()
        req.recognitionLevel = .accurate
        req.recognitionLanguages = ["zh-Hans", "en-US"]
        req.usesLanguageCorrection = false
        let handler = VNImageRequestHandler(cgImage: cg)
        guard (try? handler.perform([req])) != nil else { return }
        let lines = (req.results ?? []).compactMap { obs -> [String: Any]? in
            guard let hit = obs.topCandidates(1).first, hit.confidence >= 0.35 else { return nil }
            return ["text":hit.string, "x":obs.boundingBox.midX,"y":obs.boundingBox.midY]
        }
        let obj: [String:Any] = ["t":t,"lines":lines]
        if let data = try? JSONSerialization.data(withJSONObject: obj), let s=String(data:data,encoding:.utf8) { print(s) }
    }
}
