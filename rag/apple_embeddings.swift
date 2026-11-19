import Foundation
import NaturalLanguage

do {
    guard let model = NLEmbedding.sentenceEmbedding(for: .english) else {
        throw NSError(domain: "Apple English sentence embeddings are unavailable", code: 1)
    }
    let input = FileHandle.standardInput.readDataToEndOfFile()
    let texts = try JSONDecoder().decode([String].self, from: input)
    let vectors = try texts.map { text in
        guard let vector = model.vector(for: text) else {
            throw NSError(domain: "Could not embed an input", code: 2)
        }
        return vector
    }
    let output = try JSONEncoder().encode(vectors)
    FileHandle.standardOutput.write(output)
} catch {
    FileHandle.standardError.write(Data("\(error)\n".utf8))
    exit(1)
}
