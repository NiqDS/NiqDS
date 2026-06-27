import Foundation

/// Thin async HTTP client for the SafeWord backend. Talks only over HTTPS
/// (Constraint 6). Decodes the backend's `{ error: { code, message } }` shape
/// into a typed `APIError`.
struct APIError: Error, Equatable {
    let status: Int
    let code: String
    let message: String
}

protocol APIClienting: Sendable {
    func send<Response: Decodable>(
        _ request: APIRequest,
        bearer: String?,
        as type: Response.Type
    ) async throws -> Response

    func sendNoContent(_ request: APIRequest, bearer: String?) async throws
}

struct APIRequest {
    enum Method: String { case GET, POST, DELETE }
    let method: Method
    let path: String
    let body: Encodable?

    init(_ method: Method, _ path: String, body: Encodable? = nil) {
        self.method = method
        self.path = path
        self.body = body
    }
}

final class APIClient: APIClienting, @unchecked Sendable {
    private let baseURL: URL
    private let session: URLSession
    private let encoder = JSONEncoder()
    private let decoder = JSONDecoder()

    init(baseURL: URL, session: URLSession = .shared) {
        precondition(
            baseURL.scheme == "https" || baseURL.host == "localhost",
            "SafeWord requires HTTPS except for localhost development."
        )
        self.baseURL = baseURL
        self.session = session
        decoder.dateDecodingStrategy = .iso8601
        encoder.dateEncodingStrategy = .iso8601
    }

    private func makeURLRequest(_ request: APIRequest, bearer: String?) throws -> URLRequest {
        guard let url = URL(string: request.path, relativeTo: baseURL) else {
            throw APIError(status: 0, code: "bad_url", message: "Invalid path")
        }
        var urlRequest = URLRequest(url: url)
        urlRequest.httpMethod = request.method.rawValue
        if let bearer {
            urlRequest.setValue("Bearer \(bearer)", forHTTPHeaderField: "Authorization")
        }
        if let body = request.body {
            urlRequest.setValue("application/json", forHTTPHeaderField: "Content-Type")
            urlRequest.httpBody = try encoder.encode(AnyEncodable(body))
        }
        return urlRequest
    }

    private func validate(_ data: Data, _ response: URLResponse) throws {
        guard let http = response as? HTTPURLResponse else {
            throw APIError(status: 0, code: "no_response", message: "No HTTP response")
        }
        guard (200..<300).contains(http.statusCode) else {
            if let envelope = try? decoder.decode(ErrorEnvelope.self, from: data) {
                throw APIError(
                    status: http.statusCode,
                    code: envelope.error.code,
                    message: envelope.error.message
                )
            }
            throw APIError(
                status: http.statusCode,
                code: "http_error",
                message: "Request failed (\(http.statusCode))"
            )
        }
    }

    func send<Response: Decodable>(
        _ request: APIRequest,
        bearer: String?,
        as _: Response.Type
    ) async throws -> Response {
        let (data, response) = try await session.data(for: makeURLRequest(request, bearer: bearer))
        try validate(data, response)
        return try decoder.decode(Response.self, from: data)
    }

    func sendNoContent(_ request: APIRequest, bearer: String?) async throws {
        let (data, response) = try await session.data(for: makeURLRequest(request, bearer: bearer))
        try validate(data, response)
    }

    private struct ErrorEnvelope: Decodable {
        struct Body: Decodable { let code: String; let message: String }
        let error: Body
    }
}

/// Erases a heterogeneous `Encodable` so request bodies can be typed loosely.
private struct AnyEncodable: Encodable {
    private let encodeFunc: (Encoder) throws -> Void
    init(_ wrapped: Encodable) {
        encodeFunc = wrapped.encode
    }
    func encode(to encoder: Encoder) throws {
        try encodeFunc(encoder)
    }
}
