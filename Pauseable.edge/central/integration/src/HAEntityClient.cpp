#include "HAEntityClient.hpp"

#include <atomic>
#include <chrono>
#include <condition_variable>
#include <iostream>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string_view>
#include <thread>
#include <unordered_set>
#include <utility>

#include <boost/asio/ip/tcp.hpp>
#include <boost/beast/core.hpp>
#include <boost/beast/websocket.hpp>
#include <nlohmann/json.hpp>

namespace pauseable {
namespace {

namespace asio = boost::asio;
namespace beast = boost::beast;
namespace websocket = beast::websocket;
using tcp = asio::ip::tcp;
using Json = nlohmann::json;
using WebSocket = websocket::stream<beast::tcp_stream>;

constexpr int kGetStatesRequestId = 1;
constexpr int kSubscribeRequestId = 2;
constexpr auto kReconnectDelay = std::chrono::seconds(5);

struct ParsedWebSocketUrl
{
    std::string host;
    std::string port;
    std::string target;
    std::string hostHeader;
};

ParsedWebSocketUrl parseWebSocketUrl(const std::string& url)
{
    constexpr std::string_view scheme{"ws://"};

    if (url.compare(0, scheme.size(), scheme) != 0) {
        throw std::invalid_argument(
            "Only ws:// Home Assistant URLs are currently supported: " + url
        );
    }

    const std::string remainder = url.substr(scheme.size());
    const std::size_t pathStart = remainder.find('/');
    const std::string authority = remainder.substr(0, pathStart);
    const std::string target =
        pathStart == std::string::npos ? "/" : remainder.substr(pathStart);

    if (authority.empty()) {
        throw std::invalid_argument("The Home Assistant WebSocket URL has no host");
    }

    ParsedWebSocketUrl parsed;
    parsed.target = target;
    parsed.hostHeader = authority;

    if (authority.front() == '[') {
        const std::size_t bracketEnd = authority.find(']');
        if (bracketEnd == std::string::npos) {
            throw std::invalid_argument("Invalid IPv6 Home Assistant URL: " + url);
        }

        parsed.host = authority.substr(1, bracketEnd - 1);
        parsed.port =
            bracketEnd + 1 < authority.size() && authority[bracketEnd + 1] == ':'
                ? authority.substr(bracketEnd + 2)
                : "80";
    } else {
        const std::size_t colon = authority.rfind(':');
        if (colon == std::string::npos) {
            parsed.host = authority;
            parsed.port = "80";
        } else {
            parsed.host = authority.substr(0, colon);
            parsed.port = authority.substr(colon + 1);
        }
    }

    if (parsed.host.empty() || parsed.port.empty()) {
        throw std::invalid_argument("Invalid Home Assistant WebSocket URL: " + url);
    }

    return parsed;
}

Json readJson(WebSocket& socket)
{
    beast::flat_buffer buffer;
    socket.read(buffer);
    return Json::parse(beast::buffers_to_string(buffer.data()));
}

void writeJson(WebSocket& socket, const Json& message)
{
    const std::string payload = message.dump();
    socket.write(asio::buffer(payload));
}

std::optional<std::string> stateValue(const Json& state)
{
    if (!state.is_object()) {
        return std::nullopt;
    }

    const auto iterator = state.find("state");
    if (iterator == state.end() || !iterator->is_string()) {
        return std::nullopt;
    }

    return iterator->get<std::string>();
}

std::string contextId(const Json& value)
{
    if (!value.is_object()) {
        return {};
    }

    const auto context = value.find("context");
    if (context == value.end() || !context->is_object()) {
        return {};
    }

    return context->value("id", std::string{});
}

}

class HaEntityClient::Impl
{
public:
    Impl(
        std::string websocketUrl,
        std::string accessToken,
        std::vector<std::string> entityIds,
        EventHandler eventHandler
    )
        : websocketUrl_(std::move(websocketUrl)),
          accessToken_(std::move(accessToken)),
          entityIds_(entityIds.begin(), entityIds.end()),
          eventHandler_(std::move(eventHandler))
    {
        if (websocketUrl_.empty()) {
            throw std::invalid_argument("Home Assistant WebSocket URL must not be empty");
        }
        if (accessToken_.empty()) {
            throw std::invalid_argument("Home Assistant access token must not be empty");
        }
        if (!eventHandler_) {
            throw std::invalid_argument("Home Assistant event handler must be provided");
        }
    }

    ~Impl()
    {
        stop();
    }

    void start()
    {
        bool expected = false;
        if (!running_.compare_exchange_strong(expected, true)) {
            return;
        }

        worker_ = std::thread([this] { run(); });
    }

    void stop()
    {
        if (!running_.exchange(false)) {
            return;
        }

        reconnectCondition_.notify_all();
        interruptActiveSocket();

        if (worker_.joinable()) {
            worker_.join();
        }
    }

    bool isRunning() const
    {
        return running_.load();
    }

private:
    void run()
    {
        while (running_.load()) {
            try {
                connectAndListen();
            } catch (const std::exception& error) {
                if (running_.load()) {
                    std::cerr << "[HA] Connection error: " << error.what() << '\n';
                }
            }

            if (!running_.load()) {
                break;
            }

            std::unique_lock<std::mutex> lock(reconnectMutex_);
            reconnectCondition_.wait_for(
                lock,
                kReconnectDelay,
                [this] { return !running_.load(); }
            );
        }
    }

    void connectAndListen()
    {
        const ParsedWebSocketUrl parsed = parseWebSocketUrl(websocketUrl_);

        asio::io_context ioContext;
        tcp::resolver resolver(ioContext);
        const auto endpoints = resolver.resolve(parsed.host, parsed.port);
        auto socket = std::make_shared<WebSocket>(ioContext);

        {
            std::lock_guard<std::mutex> lock(activeSocketMutex_);
            activeSocket_ = socket;
        }

        try {
            beast::get_lowest_layer(*socket).connect(endpoints);
            socket->set_option(
                websocket::stream_base::timeout::suggested(beast::role_type::client)
            );
            socket->set_option(websocket::stream_base::decorator([](websocket::request_type& request) {
                request.set(beast::http::field::user_agent, "PAUSEABLE-Atlas/0.1");
            }));
            socket->handshake(parsed.hostHeader, parsed.target);

            authenticate(*socket);
            requestInitialStates(*socket);
            subscribeToStateChanges(*socket);

            std::cout << "[HA] Connected and subscribed to state_changed events\n";

            while (running_.load()) {
                handleMessage(readJson(*socket));
            }
        } catch (...) {
            clearActiveSocket(socket);
            throw;
        }

        clearActiveSocket(socket);
    }

    void authenticate(WebSocket& socket)
    {
        const Json authRequired = readJson(socket);
        if (authRequired.value("type", std::string{}) != "auth_required") {
            throw std::runtime_error("Home Assistant did not request authentication");
        }

        writeJson(socket, Json{
            {"type", "auth"},
            {"access_token", accessToken_}
        });

        const Json authResult = readJson(socket);
        const std::string type = authResult.value("type", std::string{});
        if (type != "auth_ok") {
            throw std::runtime_error(
                "Home Assistant authentication failed: " +
                authResult.value("message", std::string{"unknown reason"})
            );
        }
    }

    void requestInitialStates(WebSocket& socket)
    {
        writeJson(socket, Json{
            {"id", kGetStatesRequestId},
            {"type", "get_states"}
        });
    }

    void subscribeToStateChanges(WebSocket& socket)
    {
        writeJson(socket, Json{
            {"id", kSubscribeRequestId},
            {"type", "subscribe_events"},
            {"event_type", "state_changed"}
        });
    }

    void handleMessage(const Json& message)
    {
        const std::string type = message.value("type", std::string{});

        if (type == "result") {
            handleResult(message);
            return;
        }

        if (type == "event") {
            handleStateChangedEvent(message);
        }
    }

    void handleResult(const Json& message)
    {
        const int id = message.value("id", -1);
        const bool success = message.value("success", false);

        if (!success) {
            throw std::runtime_error(
                "Home Assistant command failed: " +
                message.value("error", Json::object()).dump()
            );
        }

        if (id == kGetStatesRequestId) {
            const auto result = message.find("result");
            if (result == message.end() || !result->is_array()) {
                throw std::runtime_error("Home Assistant get_states returned invalid data");
            }

            for (const Json& state : *result) {
                emitInitialState(state);
            }
        } else if (id == kSubscribeRequestId) {
            std::cout << "[HA] state_changed subscription confirmed\n";
        }
    }

    void emitInitialState(const Json& state)
    {
        if (!state.is_object()) {
            return;
        }

        const std::string entityId = state.value("entity_id", std::string{});
        if (!shouldHandle(entityId)) {
            return;
        }

        HaEntityEvent event;
        event.entityId = entityId;
        event.state = stateValue(state).value_or("unavailable");
        event.occurredAt = state.value(
            "last_changed",
            state.value("last_updated", std::string{})
        );
        event.eventId = contextId(state);
        if (event.eventId.empty()) {
            event.eventId = "initial:" + entityId + ":" + event.occurredAt;
        }

        const auto attributes = state.find("attributes");
        if (attributes != state.end() && attributes->is_object()) {
            event.attributesJson = attributes->dump();
        }

        emit(event);
    }

    void handleStateChangedEvent(const Json& message)
    {
        const auto eventIterator = message.find("event");
        if (eventIterator == message.end() || !eventIterator->is_object()) {
            return;
        }

        const Json& sourceEvent = *eventIterator;
        if (sourceEvent.value("event_type", std::string{}) != "state_changed") {
            return;
        }

        const auto dataIterator = sourceEvent.find("data");
        if (dataIterator == sourceEvent.end() || !dataIterator->is_object()) {
            return;
        }

        const Json& data = *dataIterator;
        const std::string entityId = data.value("entity_id", std::string{});
        if (!shouldHandle(entityId)) {
            return;
        }

        const Json newState = data.value("new_state", Json{});
        const Json oldState = data.value("old_state", Json{});

        HaEntityEvent event;
        event.entityId = entityId;
        event.state = stateValue(newState).value_or("unavailable");
        event.previousState = stateValue(oldState);
        const std::string newStateTime = newState.is_object()
            ? newState.value("last_changed", std::string{})
            : std::string{};
        event.occurredAt = sourceEvent.value(
            "time_fired",
            newStateTime
        );
        event.eventId = contextId(sourceEvent);
        if (event.eventId.empty()) {
            event.eventId = contextId(newState);
        }
        if (event.eventId.empty()) {
            event.eventId = entityId + ":" + event.occurredAt;
        }

        if (newState.is_object()) {
            const auto attributes = newState.find("attributes");
            if (attributes != newState.end() && attributes->is_object()) {
                event.attributesJson = attributes->dump();
            }
        }

        emit(event);
    }

    bool shouldHandle(const std::string& entityId) const
    {
        return !entityId.empty() &&
            (entityIds_.empty() || entityIds_.find(entityId) != entityIds_.end());
    }

    void emit(const HaEntityEvent& event) const
    {
        try {
            eventHandler_(event);
        } catch (const std::exception& error) {
            std::cerr << "[HA] Event handler error: " << error.what() << '\n';
        }
    }

    void interruptActiveSocket()
    {
        std::shared_ptr<WebSocket> socket;
        {
            std::lock_guard<std::mutex> lock(activeSocketMutex_);
            socket = activeSocket_;
        }

        if (!socket) {
            return;
        }

        boost::system::error_code ignored;
        auto& tcpSocket = beast::get_lowest_layer(*socket).socket();
        tcpSocket.cancel(ignored);
        tcpSocket.shutdown(tcp::socket::shutdown_both, ignored);
        tcpSocket.close(ignored);
    }

    void clearActiveSocket(const std::shared_ptr<WebSocket>& socket)
    {
        std::lock_guard<std::mutex> lock(activeSocketMutex_);
        if (activeSocket_ == socket) {
            activeSocket_.reset();
        }
    }

    std::string websocketUrl_;
    std::string accessToken_;
    std::unordered_set<std::string> entityIds_;
    EventHandler eventHandler_;

    std::atomic<bool> running_{false};
    std::thread worker_;
    std::mutex reconnectMutex_;
    std::condition_variable reconnectCondition_;
    std::mutex activeSocketMutex_;
    std::shared_ptr<WebSocket> activeSocket_;
};

HaEntityClient::HaEntityClient(
    std::string websocketUrl,
    std::string accessToken,
    std::vector<std::string> entityIds,
    EventHandler eventHandler
)
    : impl_(std::make_unique<Impl>(
          std::move(websocketUrl),
          std::move(accessToken),
          std::move(entityIds),
          std::move(eventHandler)
      ))
{
}

HaEntityClient::~HaEntityClient() = default;

void HaEntityClient::start()
{
    impl_->start();
}

void HaEntityClient::stop()
{
    impl_->stop();
}

bool HaEntityClient::isRunning() const
{
    return impl_->isRunning();
}

}
