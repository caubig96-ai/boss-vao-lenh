import Foundation

enum BossAPIError: LocalizedError {
    case badURL
    case unauthorized
    case server(String)
    case invalidResponse

    var errorDescription: String? {
        switch self {
        case .badURL:
            return "Địa chỉ Boss Cloud không hợp lệ."
        case .unauthorized:
            return "Sai mật khẩu Boss Cloud."
        case .server(let message):
            return message
        case .invalidResponse:
            return "Cloud trả về dữ liệu không hợp lệ."
        }
    }
}

struct BossAPIClient {
    let baseURL: String
    let password: String

    private var normalizedBaseURL: String {
        var value = baseURL.trimmingCharacters(in: .whitespacesAndNewlines)
        while value.hasSuffix("/") { value.removeLast() }
        return value
    }

    private func request(path: String, method: String = "GET", body: Data? = nil) throws -> URLRequest {
        guard let url = URL(string: normalizedBaseURL + path) else {
            throw BossAPIError.badURL
        }
        var request = URLRequest(url: url)
        request.httpMethod = method
        request.timeoutInterval = 15
        request.cachePolicy = .reloadIgnoringLocalAndRemoteCacheData
        request.setValue("Bearer \(password)", forHTTPHeaderField: "Authorization")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        if body != nil {
            request.setValue("application/json", forHTTPHeaderField: "Content-Type")
            request.httpBody = body
        }
        return request
    }

    private func execute<T: Decodable>(_ request: URLRequest, as type: T.Type) async throws -> T {
        let (data, response) = try await URLSession.shared.data(for: request)
        guard let http = response as? HTTPURLResponse else {
            throw BossAPIError.invalidResponse
        }
        if http.statusCode == 401 {
            throw BossAPIError.unauthorized
        }
        guard (200..<300).contains(http.statusCode) else {
            if let action = try? JSONDecoder().decode(BossActionResponse.self, from: data),
               let message = action.error {
                throw BossAPIError.server(message)
            }
            let body = String(data: data, encoding: .utf8) ?? "HTTP \(http.statusCode)"
            throw BossAPIError.server(body)
        }

        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        do {
            return try decoder.decode(T.self, from: data)
        } catch {
            throw BossAPIError.invalidResponse
        }
    }

    func status() async throws -> BossStatus {
        let req = try request(path: "/api/status")
        return try await execute(req, as: BossStatus.self)
    }

    func saveSettings(_ payload: BossSettingsPayload) async throws {
        let data = try JSONEncoder().encode(payload)
        let req = try request(path: "/api/settings", method: "POST", body: data)
        _ = try await execute(req, as: BossActionResponse.self)
    }

    func testTelegram() async throws {
        let req = try request(path: "/api/test-telegram", method: "POST")
        _ = try await execute(req, as: BossActionResponse.self)
    }
}
