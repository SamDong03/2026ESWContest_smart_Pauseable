#include "DecisionGatewayClient.hpp"

#include <algorithm>
#include <cctype>
#include <stdexcept>
#include <string_view>
#include <utility>

#include <boost/asio/connect.hpp>
#include <boost/asio/ip/tcp.hpp>
#include <boost/asio/ssl.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/http.hpp>
#include <boost/beast/ssl.hpp>
#include <openssl/ssl.h>

namespace pauseable {
namespace {

namespace asio = boost::asio;
namespace beast = boost::beast;
namespace http = beast::http;
namespace ssl = asio::ssl;
using tcp = asio::ip::tcp;

struct ParsedUrl {
    bool secure{false};
    std::string host;
    std::string port;
    std::string target;
    std::string hostHeader;
};

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
        throw std::invalid_argument("Decision Gateway URL must use http:// or https://");
    }

    const std::string remainder = url.substr(schemeLength);
    const std::size_t pathStart = remainder.find('/');
    const std::string authority = remainder.substr(0, pathStart);
    if (authority.empty()) throw std::invalid_argument("Decision Gateway URL has no host");
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
        throw std::invalid_argument("Decision Gateway URL has an invalid authority");
    }
    return parsed;
}

http::request<http::string_body> makeRequest(
    const ParsedUrl& parsed,
    const DecisionGatewayConfig& config,
    const std::string& eventId,
    const std::string& payload)
{
    http::request<http::string_body> request{http::verb::post, parsed.target, 11};
    request.set(http::field::host, parsed.hostHeader);
    request.set(http::field::user_agent, "Pauseable-Central-Atlas/0.2");
    request.set(http::field::content_type, "application/json");
    request.set(http::field::authorization, "Bearer " + config.bearerToken);
    request.set("Idempotency-Key", eventId);
    request.body() = payload;
    request.prepare_payload();
    return request;
}

std::string boundedDetail(const std::string& value)
{
    constexpr std::size_t maximum = 256;
    return value.size() <= maximum ? value : value.substr(0, maximum);
}

std::chrono::seconds retryAfterFor(const http::response<http::string_body>& response)
{
    const auto header = response.find(http::field::retry_after);
    if (header == response.end()) return std::chrono::seconds(0);
    const std::string text(header->value().data(), header->value().size());
    if (text.empty() || std::any_of(text.begin(), text.end(), [](unsigned char value) {
            return std::isdigit(value) == 0;
        })) {
        return std::chrono::seconds(0);
    }
    try {
        return std::chrono::seconds(std::min<unsigned long>(std::stoul(text), 300));
    } catch (...) {
        return std::chrono::seconds(0);
    }
}

OutboxDeliveryResult classify(const http::response<http::string_body>& response)
{
    OutboxDeliveryResult result;
    result.statusCode = response.result_int();
    result.detail = boundedDetail(response.body());
    result.retryAfter = retryAfterFor(response);
    if (result.statusCode == 200 || result.statusCode == 202) {
        result.disposition = OutboxDeliveryDisposition::Delivered;
    } else if (result.statusCode == 429 || result.statusCode >= 500) {
        result.disposition = OutboxDeliveryDisposition::RetryableFailure;
    } else {
        result.disposition = OutboxDeliveryDisposition::PermanentFailure;
    }
    return result;
}

http::response<http::string_body> postPlain(
    const ParsedUrl& parsed,
    const DecisionGatewayConfig& config,
    const std::string& eventId,
    const std::string& payload)
{
    asio::io_context context;
    tcp::resolver resolver(context);
    beast::tcp_stream stream(context);
    stream.expires_after(config.timeout);
    stream.connect(resolver.resolve(parsed.host, parsed.port));
    const auto request = makeRequest(parsed, config, eventId, payload);
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
    const DecisionGatewayConfig& config,
    const std::string& eventId,
    const std::string& payload)
{
    asio::io_context context;
    ssl::context tlsContext(ssl::context::tls_client);
    tlsContext.set_default_verify_paths();
    beast::ssl_stream<beast::tcp_stream> stream(context, tlsContext);
    if (!SSL_set_tlsext_host_name(stream.native_handle(), parsed.host.c_str())) {
        throw std::runtime_error("Could not configure TLS server name");
    }
    stream.set_verify_mode(ssl::verify_peer);
    stream.set_verify_callback(ssl::rfc2818_verification(parsed.host));

    beast::get_lowest_layer(stream).expires_after(config.timeout);
    beast::get_lowest_layer(stream).connect(
        tcp::resolver(context).resolve(parsed.host, parsed.port));
    stream.handshake(ssl::stream_base::client);

    const auto request = makeRequest(parsed, config, eventId, payload);
    http::write(stream, request);
    beast::flat_buffer buffer;
    http::response<http::string_body> response;
    http::read(stream, buffer, response);

    boost::system::error_code ignored;
    stream.shutdown(ignored);
    return response;
}

}

DecisionGatewayClient::DecisionGatewayClient(DecisionGatewayConfig config)
    : config_(std::move(config))
{
    if (config_.eventUrl.empty() || config_.bearerToken.empty() ||
        config_.timeout.count() <= 0) {
        throw std::invalid_argument("Decision Gateway configuration is incomplete");
    }
    (void)parseUrl(config_.eventUrl);
}

OutboxDeliveryResult DecisionGatewayClient::publish(
    const std::string& eventId,
    const std::string& payload) const
{
    const ParsedUrl parsed = parseUrl(config_.eventUrl);
    return classify(parsed.secure
        ? postTls(parsed, config_, eventId, payload)
        : postPlain(parsed, config_, eventId, payload));
}

}
