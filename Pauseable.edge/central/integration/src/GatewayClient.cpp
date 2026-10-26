#include "GatewayClient.hpp"

#include <stdexcept>
#include <string_view>
#include <utility>

#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/asio/ssl.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/ssl.hpp>
#include <nlohmann/json.hpp>
#include <openssl/ssl.h>

namespace pauseable {
namespace {

namespace asio = boost::asio;
namespace beast = boost::beast;
namespace http = beast::http;
namespace ssl = asio::ssl;
using tcp = asio::ip::tcp;
using Json = nlohmann::json;

struct ParsedUrl
{
    bool secure{false};
    std::string host;
    std::string port;
    std::string target;
    std::string hostHeader;
};

Json attributesFor(const HaEntityEvent& event);

ParsedUrl parseUrl(const std::string& url)
{
    constexpr std::string_view httpScheme{"http://"};
    constexpr std::string_view httpsScheme{"https://"};
    ParsedUrl parsed;
    std::size_t schemeLength = 0;
    if (url.compare(0, httpsScheme.size(), httpsScheme) == 0) {
        parsed.secure = true;
        schemeLength = httpsScheme.size();
    } else if (url.compare(0, httpScheme.size(), httpScheme) == 0) {
        schemeLength = httpScheme.size();
    } else {
        throw std::invalid_argument("Gateway URL must use http:// or https://");
    }

    const std::string remainder = url.substr(schemeLength);
    const std::size_t pathStart = remainder.find('/');
    const std::string authority = remainder.substr(0, pathStart);
    if (authority.empty()) {
        throw std::invalid_argument("The Gateway URL has no host");
    }

    parsed.hostHeader = authority;
    parsed.target = pathStart == std::string::npos ? "/" : remainder.substr(pathStart);

    const std::size_t colon = authority.rfind(':');
    if (colon == std::string::npos) {
        parsed.host = authority;
        parsed.port = parsed.secure ? "443" : "80";
    } else {
        parsed.host = authority.substr(0, colon);
        parsed.port = authority.substr(colon + 1);
    }

    if (parsed.host.empty() || parsed.port.empty()) {
        throw std::invalid_argument("Invalid Gateway URL: " + url);
    }
    return parsed;
}

http::request<http::string_body> makeRequest(
    const ParsedUrl& parsed,
    const GatewayConfig& config,
    const HaEntityEvent& event)
{
    Json payload{
        {"patient_id", config.patientId},
        {"event_id", event.eventId},
        {"occurred_at", event.occurredAt},
        {"source", event.source},
        {"entity_id", event.entityId},
        {"state", event.state},
        {"attributes", attributesFor(event)},
    };
    if (event.previousState.has_value()) {
        payload["previous_state"] = *event.previousState;
    } else {
        payload["previous_state"] = nullptr;
    }

    http::request<http::string_body> request{http::verb::post, parsed.target, 11};
    request.set(http::field::host, parsed.hostHeader);
    request.set(http::field::user_agent, "Pauseable-Central-Atlas/0.2");
    request.set(http::field::content_type, "application/json");
    request.set(http::field::authorization, "Bearer " + config.bearerToken);
    request.set("Idempotency-Key", event.eventId);
    request.body() = payload.dump();
    request.prepare_payload();
    return request;
}

http::response<http::string_body> postPlain(
    const ParsedUrl& parsed,
    const GatewayConfig& config,
    const HaEntityEvent& event)
{
    asio::io_context context;
    tcp::resolver resolver(context);
    beast::tcp_stream stream(context);
    stream.expires_after(config.timeout);
    stream.connect(resolver.resolve(parsed.host, parsed.port));
    const auto request = makeRequest(parsed, config, event);
    http::write(stream, request);

    beast::flat_buffer buffer;
    http::response<http::string_body> response;
    http::read(stream, buffer, response);
    boost::system::error_code ignored;
    stream.socket().shutdown(tcp::socket::shutdown_both, ignored);
    return response;
}

http::response<http::string_body> postTls(
    const ParsedUrl& parsed,
    const GatewayConfig& config,
    const HaEntityEvent& event)
{
    asio::io_context context;
    ssl::context tlsContext(ssl::context::tls_client);
    tlsContext.set_default_verify_paths();
    beast::ssl_stream<beast::tcp_stream> stream(context, tlsContext);
    if (!SSL_set_tlsext_host_name(stream.native_handle(), parsed.host.c_str())) {
        throw std::runtime_error("Could not configure Gateway TLS server name");
    }
    stream.set_verify_mode(ssl::verify_peer);
    stream.set_verify_callback(ssl::rfc2818_verification(parsed.host));

    beast::get_lowest_layer(stream).expires_after(config.timeout);
    beast::get_lowest_layer(stream).connect(
        tcp::resolver(context).resolve(parsed.host, parsed.port));
    stream.handshake(ssl::stream_base::client);

    const auto request = makeRequest(parsed, config, event);
    http::write(stream, request);
    beast::flat_buffer buffer;
    http::response<http::string_body> response;
    http::read(stream, buffer, response);

    boost::system::error_code ignored;
    stream.shutdown(ignored);
    return response;
}

Json attributesFor(const HaEntityEvent& event)
{
    try {
        const Json attributes = Json::parse(event.attributesJson);
        return attributes.is_object() ? attributes : Json::object();
    } catch (const Json::exception&) {
        return Json::object();
    }
}

}

GatewayClient::GatewayClient(GatewayConfig config)
    : config_(std::move(config))
{
    if (config_.eventUrl.empty() || config_.bearerToken.empty() ||
        config_.patientId.empty() || config_.timeout.count() <= 0) {
        throw std::invalid_argument("Gateway configuration is incomplete");
    }
    (void)parseUrl(config_.eventUrl);
}

GatewayPublishResult GatewayClient::publish(const HaEntityEvent& event) const
{
    const ParsedUrl parsed = parseUrl(config_.eventUrl);
    const auto response = parsed.secure
        ? postTls(parsed, config_, event)
        : postPlain(parsed, config_, event);

    if (response.result_int() < 200 || response.result_int() >= 300) {
        throw std::runtime_error(
            "Gateway returned HTTP " + std::to_string(response.result_int()) +
            ": " + response.body()
        );
    }

    const Json responseJson = Json::parse(response.body());
    const Json alert = responseJson.value("alert", Json::object());
    const Json voice = responseJson.value("voice", Json::object());

    GatewayPublishResult result;
    result.status = responseJson.value("status", std::string{});
    result.alertTitle = alert.value("title", std::string{});
    result.voiceStatus = voice.value("status", std::string{});
    result.audioUrl = voice.value("audio_url", std::string{});
    return result;
}

}
