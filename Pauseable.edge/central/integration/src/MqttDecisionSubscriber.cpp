#include "MqttDecisionSubscriber.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <chrono>
#include <cstddef>
#include <cstdint>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <thread>
#include <utility>
#include <vector>

#include <boost/asio.hpp>

namespace pauseable {
namespace {

using ByteVector = std::vector<std::uint8_t>;
using Tcp = boost::asio::ip::tcp;

void appendUint16(ByteVector& output, std::uint16_t value)
{
    output.push_back(static_cast<std::uint8_t>((value >> 8) & 0xff));
    output.push_back(static_cast<std::uint8_t>(value & 0xff));
}

void appendUtf8(ByteVector& output, const std::string& value)
{
    if (value.size() > 65535) {
        throw std::invalid_argument("MQTT UTF-8 field is too long");
    }
    appendUint16(output, static_cast<std::uint16_t>(value.size()));
    output.insert(output.end(), value.begin(), value.end());
}

ByteVector encodeRemainingLength(std::size_t value)
{
    if (value > 268435455) {
        throw std::invalid_argument("MQTT packet is too large");
    }
    ByteVector output;
    do {
        std::uint8_t byte = static_cast<std::uint8_t>(value % 128);
        value /= 128;
        if (value > 0) byte |= 0x80;
        output.push_back(byte);
    } while (value > 0);
    return output;
}

ByteVector packet(std::uint8_t header, const ByteVector& body)
{
    ByteVector output{header};
    const auto remaining = encodeRemainingLength(body.size());
    output.insert(output.end(), remaining.begin(), remaining.end());
    output.insert(output.end(), body.begin(), body.end());
    return output;
}

ByteVector connectPacket(const MqttDecisionSubscriberConfig& config)
{
    ByteVector body;
    appendUtf8(body, "MQTT");
    body.push_back(4);
    std::uint8_t flags = 0x02;
    if (!config.username.empty()) flags |= 0x80;
    if (!config.password.empty()) flags |= 0x40;
    body.push_back(flags);
    appendUint16(body, config.keepAliveSeconds);
    appendUtf8(body, config.clientId);
    if (!config.username.empty()) appendUtf8(body, config.username);
    if (!config.password.empty()) appendUtf8(body, config.password);
    return packet(0x10, body);
}

ByteVector subscribePacket(const std::vector<std::string>& topics, std::uint16_t packetId)
{
    ByteVector body;
    appendUint16(body, packetId);
    for (const auto& topic : topics) {
        appendUtf8(body, topic);
        body.push_back(1);
    }
    return packet(0x82, body);
}

struct DecodedPacket {
    std::uint8_t header{};
    ByteVector body;
};

std::optional<DecodedPacket> takePacket(ByteVector& buffer)
{
    constexpr std::size_t maximumPacketBytes = 1024 * 1024;
    if (buffer.size() < 2) return std::nullopt;

    std::size_t multiplier = 1;
    std::size_t remaining = 0;
    std::size_t offset = 1;
    std::uint8_t encoded{};
    do {
        if (offset > 4) throw std::runtime_error("Invalid MQTT remaining length");
        if (offset >= buffer.size()) return std::nullopt;
        encoded = buffer[offset++];
        remaining += (encoded & 0x7f) * multiplier;
        multiplier *= 128;
    } while ((encoded & 0x80) != 0);

    if (remaining > maximumPacketBytes) {
        throw std::runtime_error("MQTT packet exceeds the configured safety limit");
    }

    if (buffer.size() < offset + remaining) return std::nullopt;
    DecodedPacket result;
    result.header = buffer[0];
    result.body.assign(buffer.begin() + static_cast<std::ptrdiff_t>(offset),
                       buffer.begin() + static_cast<std::ptrdiff_t>(offset + remaining));
    buffer.erase(buffer.begin(), buffer.begin() + static_cast<std::ptrdiff_t>(offset + remaining));
    return result;
}

std::uint16_t readUint16(const ByteVector& input, std::size_t offset)
{
    if (offset + 2 > input.size()) throw std::runtime_error("Truncated MQTT uint16");
    return static_cast<std::uint16_t>((input[offset] << 8) | input[offset + 1]);
}

}

struct MqttDecisionSubscriber::Impl {
    MqttDecisionSubscriberConfig config;
    MessageHandler messageHandler;
    StatusHandler statusHandler;
    std::atomic<bool> active{false};
    std::atomic<bool> stopRequested{false};
    std::thread worker;
    mutable std::mutex socketMutex;
    std::shared_ptr<Tcp::socket> socket;

    Impl(MqttDecisionSubscriberConfig value, MessageHandler message, StatusHandler status)
        : config(std::move(value)), messageHandler(std::move(message)), statusHandler(std::move(status))
    {
        if (config.host.empty() || config.port == 0 || config.clientId.empty() ||
            config.topics.empty() || !messageHandler || !statusHandler) {
            throw std::invalid_argument("MQTT subscriber configuration is incomplete");
        }
        if (config.username.empty() != config.password.empty()) {
            throw std::invalid_argument("MQTT username and password must be configured together");
        }
    }

    ~Impl()
    {
        stop();
    }

    void report(const std::string& state, const std::string& detail) noexcept
    {
        try {
            statusHandler(state, detail);
        } catch (...) {
        }
    }

    void start()
    {
        bool expected = false;
        if (!active.compare_exchange_strong(expected, true)) return;
        stopRequested = false;
        worker = std::thread([this] { run(); });
    }

    void stop() noexcept
    {
        stopRequested = true;
        {
            std::lock_guard<std::mutex> lock(socketMutex);
            if (socket) {
                boost::system::error_code ignored;
                socket->shutdown(Tcp::socket::shutdown_both, ignored);
                socket->close(ignored);
            }
        }
        if (worker.joinable()) worker.join();
        active = false;
    }

    bool waitForStop(std::chrono::milliseconds duration)
    {
        constexpr auto slice = std::chrono::milliseconds(100);
        while (duration.count() > 0 && !stopRequested) {
            const auto current = std::min(duration, slice);
            std::this_thread::sleep_for(current);
            duration -= current;
        }
        return stopRequested;
    }

    void write(const std::shared_ptr<Tcp::socket>& connection, const ByteVector& bytes)
    {
        boost::asio::write(*connection, boost::asio::buffer(bytes));
    }

    DecodedPacket waitForPacket(
        const std::shared_ptr<Tcp::socket>& connection,
        ByteVector& buffer,
        std::chrono::steady_clock::time_point deadline)
    {
        std::array<std::uint8_t, 4096> chunk{};
        while (!stopRequested && std::chrono::steady_clock::now() < deadline) {
            if (auto decoded = takePacket(buffer)) return std::move(*decoded);
            boost::system::error_code error;
            const auto count = connection->read_some(boost::asio::buffer(chunk), error);
            if (!error) {
                buffer.insert(buffer.end(), chunk.begin(), chunk.begin() + count);
                continue;
            }
            if (error == boost::asio::error::would_block ||
                error == boost::asio::error::try_again) {
                waitForStop(std::chrono::milliseconds(20));
                continue;
            }
            throw boost::system::system_error(error);
        }
        throw std::runtime_error("Timed out waiting for MQTT broker response");
    }

    void handlePublish(
        const std::shared_ptr<Tcp::socket>& connection,
        const DecodedPacket& incoming)
    {
        const int qos = static_cast<int>((incoming.header >> 1) & 0x03);
        const bool retained = (incoming.header & 0x01) != 0;
        const bool duplicate = (incoming.header & 0x08) != 0;
        if (incoming.body.size() < 2) throw std::runtime_error("Truncated MQTT PUBLISH");
        const std::size_t topicLength = readUint16(incoming.body, 0);
        std::size_t offset = 2;
        if (offset + topicLength > incoming.body.size()) {
            throw std::runtime_error("Truncated MQTT topic");
        }
        const std::string topic(
            incoming.body.begin() + static_cast<std::ptrdiff_t>(offset),
            incoming.body.begin() + static_cast<std::ptrdiff_t>(offset + topicLength));
        offset += topicLength;

        std::uint16_t packetId = 0;
        if (qos > 0) {
            packetId = readUint16(incoming.body, offset);
            offset += 2;
        }
        const std::string payload(
            incoming.body.begin() + static_cast<std::ptrdiff_t>(offset), incoming.body.end());

        messageHandler({topic, payload, qos, retained, duplicate});
        if (qos == 1) {
            ByteVector acknowledgmentBody;
            appendUint16(acknowledgmentBody, packetId);
            write(connection, packet(0x40, acknowledgmentBody));
        }
    }

    void connectedSession()
    {
        boost::asio::io_context context;
        Tcp::resolver resolver(context);
        auto connection = std::make_shared<Tcp::socket>(context);
        {
            std::lock_guard<std::mutex> lock(socketMutex);
            socket = connection;
        }

        const auto endpoints = resolver.resolve(config.host, std::to_string(config.port));
        boost::asio::connect(*connection, endpoints);
        connection->non_blocking(true);

        ByteVector input;
        write(connection, connectPacket(config));
        const auto connack = waitForPacket(
            connection, input, std::chrono::steady_clock::now() + std::chrono::seconds(10));
        if ((connack.header >> 4) != 2 || connack.body.size() != 2 || connack.body[1] != 0) {
            throw std::runtime_error("MQTT broker rejected CONNECT");
        }

        constexpr std::uint16_t subscribeId = 1;
        write(connection, subscribePacket(config.topics, subscribeId));
        const auto suback = waitForPacket(
            connection, input, std::chrono::steady_clock::now() + std::chrono::seconds(10));
        if ((suback.header >> 4) != 9 || suback.body.size() != 2 + config.topics.size() ||
            readUint16(suback.body, 0) != subscribeId ||
            std::any_of(suback.body.begin() + 2, suback.body.end(), [](std::uint8_t value) {
                return value == 0x80;
            })) {
            throw std::runtime_error("MQTT broker rejected SUBSCRIBE");
        }
        report("connected", config.host + ":" + std::to_string(config.port));

        auto lastNetworkActivity = std::chrono::steady_clock::now();
        std::array<std::uint8_t, 4096> chunk{};
        while (!stopRequested) {
            while (auto incoming = takePacket(input)) {
                lastNetworkActivity = std::chrono::steady_clock::now();
                const auto type = incoming->header >> 4;
                if (type == 3) handlePublish(connection, *incoming);
                if (type == 13) report("ping", "response");
            }

            boost::system::error_code error;
            const auto count = connection->read_some(boost::asio::buffer(chunk), error);
            if (!error) {
                input.insert(input.end(), chunk.begin(), chunk.begin() + count);
                lastNetworkActivity = std::chrono::steady_clock::now();
                continue;
            }
            if (error != boost::asio::error::would_block &&
                error != boost::asio::error::try_again) {
                throw boost::system::system_error(error);
            }

            const auto pingAfter = std::chrono::seconds(std::max<int>(10, config.keepAliveSeconds / 2));
            if (std::chrono::steady_clock::now() - lastNetworkActivity >= pingAfter) {
                write(connection, ByteVector{0xc0, 0x00});
                lastNetworkActivity = std::chrono::steady_clock::now();
            }
            waitForStop(std::chrono::milliseconds(50));
        }
    }

    void run() noexcept
    {
        unsigned int backoffSeconds = 1;
        while (!stopRequested) {
            try {
                report("connecting", config.host + ":" + std::to_string(config.port));
                connectedSession();
                backoffSeconds = 1;
            } catch (const std::exception& error) {
                if (!stopRequested) report("disconnected", error.what());
            }

            {
                std::lock_guard<std::mutex> lock(socketMutex);
                socket.reset();
            }
            if (waitForStop(std::chrono::seconds(backoffSeconds))) break;
            backoffSeconds = std::min(30U, backoffSeconds * 2U);
        }
        active = false;
        report("stopped", "subscriber stopped");
    }
};

MqttDecisionSubscriber::MqttDecisionSubscriber(
    MqttDecisionSubscriberConfig config,
    MessageHandler messageHandler,
    StatusHandler statusHandler)
    : impl_(std::make_unique<Impl>(
          std::move(config), std::move(messageHandler), std::move(statusHandler)))
{
}

MqttDecisionSubscriber::~MqttDecisionSubscriber() = default;
void MqttDecisionSubscriber::start() { impl_->start(); }
void MqttDecisionSubscriber::stop() noexcept { impl_->stop(); }
bool MqttDecisionSubscriber::running() const noexcept { return impl_->active; }

}
