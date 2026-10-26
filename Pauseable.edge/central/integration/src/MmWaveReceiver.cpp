#include "MmWaveReceiver.hpp"
#include "MmWaveContract.hpp"
#include "MmWaveTracker.hpp"
#include <array>
#include <atomic>
#include <chrono>
#include <ctime>
#include <iomanip>
#include <sstream>
#include <stdexcept>
#include <thread>
#include <utility>

#ifdef _WIN32
#ifndef NOMINMAX
#define NOMINMAX
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#else
#include <arpa/inet.h>
#include <cerrno>
#include <fcntl.h>
#include <sys/select.h>
#include <sys/socket.h>
#include <unistd.h>
#endif

namespace pauseable {
namespace {
using Clock = std::chrono::steady_clock;
std::uint64_t monoMs() {
    return static_cast<std::uint64_t>(std::chrono::duration_cast<std::chrono::milliseconds>(
        Clock::now().time_since_epoch()).count());
}
std::string utcNow() {
    const auto now = std::chrono::system_clock::now();
    const auto seconds = std::chrono::system_clock::to_time_t(now);
    std::tm utc{};
#ifdef _WIN32
    gmtime_s(&utc, &seconds);
#else
    gmtime_r(&seconds, &utc);
#endif
    std::ostringstream out;
    out << std::put_time(&utc, "%Y-%m-%dT%H:%M:%S") << '.' << std::setfill('0') << std::setw(3)
        << (std::chrono::duration_cast<std::chrono::milliseconds>(now.time_since_epoch()).count() % 1000)
        << 'Z';
    return out.str();
}
#ifdef _WIN32
using Socket = SOCKET;
constexpr Socket badSocket = INVALID_SOCKET;
int lastSocketError() { return WSAGetLastError(); }
void closeSocket(Socket fd) { closesocket(fd); }
bool retryable(int code) { return code == WSAEWOULDBLOCK || code == WSAEINTR; }
#else
using Socket = int;
constexpr Socket badSocket = -1;
int lastSocketError() { return errno; }
void closeSocket(Socket fd) { close(fd); }
bool retryable(int code) { return code == EAGAIN || code == EWOULDBLOCK || code == EINTR; }
#endif
std::runtime_error socketError(const std::string& operation) {
    return std::runtime_error(operation + " failed (socket error " + std::to_string(lastSocketError()) + ")");
}
}

struct MmWaveReceiver::Impl {
    MmWaveReceiverConfig config;
    Reporter reporter;
    MmWaveTracker tracker;
    Socket socket = badSocket;
    std::uint16_t bound = 0;
    std::atomic<bool> active{false}, stopping{false};
    std::thread worker;
    std::uint64_t received = 0, invalid = 0, oversize = 0, peerRejected = 0, rateLimited = 0, callbackErrors = 0;
#ifdef _WIN32
    bool winsockReady = false;
#endif
    Impl(MmWaveReceiverConfig value, Reporter callback)
        : config(std::move(value)), reporter(std::move(callback)),
          tracker(MmWaveTrackerConfig{config.staleAfterMs, 64, 64}) {
        if (!reporter || config.summaryEveryMs < 10 || config.summaryEveryMs > 60000 ||
            config.staleAfterMs == 0 || config.staleAfterMs > 3600000 ||
            config.maxPacketsPerSecond == 0 || config.maxPacketsPerSecond > 10000) {
            throw std::invalid_argument("Invalid mmWave receiver configuration");
        }
#ifdef _WIN32
        WSADATA data{};
        if (WSAStartup(MAKEWORD(2, 2), &data) != 0) throw std::runtime_error("WSAStartup failed");
        winsockReady = true;
#endif
    }
    ~Impl() {
        stop();
#ifdef _WIN32
        if (winsockReady) WSACleanup();
#endif
    }
    void emit(const nlohmann::json& report) noexcept {
        try { reporter(report); } catch (...) { ++callbackErrors; }
    }
    void summary(const char* kind) {
        auto report = tracker.snapshot(monoMs());
        report["kind"] = kind;
        report["received_at"] = utcNow();
        report["transport"] = {{"datagrams", received}, {"invalid", invalid}, {"oversize", oversize},
            {"peer_rejected", peerRejected}, {"rate_limited", rateLimited}, {"callback_errors", callbackErrors}};
        emit(report);
    }
    void reject(const char* reason, const std::string& peer, const std::string& detail = "") {
        emit({{"kind", "mmwave_rejected"}, {"accepted", false}, {"reason", reason},
              {"peer", peer}, {"received_at", utcNow()}, {"detail", detail}});
    }
    void start() {
        if (active || worker.joinable()) throw std::logic_error("Receiver already started; stop before restarting");
        in_addr allowed{};
        sockaddr_in address{};
        address.sin_family = AF_INET;
        address.sin_port = htons(config.port);
        if (inet_pton(AF_INET, config.bindAddress.c_str(), &address.sin_addr) != 1 ||
            (!config.allowPeer.empty() && inet_pton(AF_INET, config.allowPeer.c_str(), &allowed) != 1)) {
            throw std::invalid_argument("Bind/allow-peer must be an IPv4 address");
        }
        socket = ::socket(AF_INET, SOCK_DGRAM, IPPROTO_UDP);
        if (socket == badSocket) throw socketError("socket");
        try {
#ifdef _WIN32
            BOOL exclusive = TRUE;
            if (setsockopt(socket, SOL_SOCKET, SO_EXCLUSIVEADDRUSE,
                           reinterpret_cast<const char*>(&exclusive), sizeof(exclusive)) != 0)
                throw socketError("exclusive bind");
            u_long nonblocking = 1;
            if (ioctlsocket(socket, FIONBIO, &nonblocking) != 0) throw socketError("nonblocking");
#else
            if (socket >= FD_SETSIZE) throw std::runtime_error("Socket exceeds select descriptor limit");
            if (fcntl(socket, F_SETFD, FD_CLOEXEC) == -1 || fcntl(socket, F_SETFL, O_NONBLOCK) == -1)
                throw socketError("fcntl");
#endif
            if (::bind(socket, reinterpret_cast<sockaddr*>(&address), sizeof(address)) != 0)
                throw socketError("UDP bind (another receiver may own the port)");
#ifdef _WIN32
            int length = sizeof(address);
#else
            socklen_t length = sizeof(address);
#endif
            if (getsockname(socket, reinterpret_cast<sockaddr*>(&address), &length) != 0)
                throw socketError("getsockname");
            bound = ntohs(address.sin_port);
            tracker = MmWaveTracker(MmWaveTrackerConfig{config.staleAfterMs, 64, 64});
            received = invalid = oversize = peerRejected = rateLimited = callbackErrors = 0;
            stopping = false;
            active = true;

            emit({{"kind", "mmwave_ready"}, {"address", config.bindAddress}, {"port", bound},
                  {"stale_after_ms", config.staleAfterMs}, {"received_at", utcNow()}});
            worker = std::thread([this] { loop(); });
        } catch (...) {
            active = false;
            closeSocket(socket);
            socket = badSocket;
            throw;
        }
    }
    void loop() noexcept {
        try {
            auto lastSummary = monoMs(), windowStart = lastSummary;
            unsigned windowPackets = 0;
            while (!stopping) {
                const auto now = monoMs();
                if (now - lastSummary >= config.summaryEveryMs) {
                    summary("mmwave_summary");
                    lastSummary = now;
                }
                fd_set ready;
                FD_ZERO(&ready);
                FD_SET(socket, &ready);
                timeval timeout{};
                timeout.tv_usec = 50000;
#ifdef _WIN32
                const int available = select(0, &ready, nullptr, nullptr, &timeout);
#else
                const int available = select(socket + 1, &ready, nullptr, nullptr, &timeout);
#endif
                if (available < 0) {
                    if (retryable(lastSocketError())) continue;
                    throw socketError("select");
                }
                if (!available) continue;
                std::array<char, kMmWaveMaxPacketBytes + 1> data{};
                sockaddr_in peerAddress{};
#ifdef _WIN32
                int peerLength = sizeof(peerAddress);
#else
                socklen_t peerLength = sizeof(peerAddress);
#endif
                const auto size = recvfrom(socket, data.data(), static_cast<int>(data.size()), 0,
                    reinterpret_cast<sockaddr*>(&peerAddress), &peerLength);
                bool truncated = false;
                if (size < 0) {
                    const int code = lastSocketError();
#ifdef _WIN32
                    truncated = code == WSAEMSGSIZE;
#endif
                    if (!truncated) {
                        if (retryable(code)) continue;
                        throw socketError("recvfrom");
                    }
                }
                ++received;
                const auto receivedMono = monoMs();
                if (receivedMono - windowStart >= 1000) { windowStart = receivedMono; windowPackets = 0; }
                if (++windowPackets > config.maxPacketsPerSecond) { ++rateLimited; continue; }
                std::array<char, INET_ADDRSTRLEN> ip{};
                if (inet_ntop(AF_INET, &peerAddress.sin_addr, ip.data(), ip.size()) == nullptr)
                    throw socketError("inet_ntop");
                const std::string peer = std::string(ip.data()) + ":" + std::to_string(ntohs(peerAddress.sin_port));
                if (!config.allowPeer.empty() && config.allowPeer != ip.data()) {
                    ++peerRejected; reject("peer_rejected", peer); continue;
                }
                if (truncated || size > static_cast<decltype(size)>(kMmWaveMaxPacketBytes)) {
                    ++oversize; reject("oversize", peer); continue;
                }
                nlohmann::json event;
                try {
                    event = parseMmWavePacket(std::string(data.data(), static_cast<std::size_t>(size)));
                } catch (const std::invalid_argument& error) {
                    ++invalid; reject("invalid_packet", peer, error.what()); continue;
                }
                emit(tracker.ingest(event, receivedMono, utcNow(), peer));
            }
            summary("mmwave_stopped");
        } catch (const std::exception& error) {
            emit({{"kind", "mmwave_error"}, {"detail", error.what()}});
        } catch (...) {
            emit({{"kind", "mmwave_error"}, {"detail", "Unknown receiver error"}});
        }
        active = false;
    }
    void stop() noexcept {
        stopping = true;
        if (worker.joinable()) worker.join();
        if (socket != badSocket) { closeSocket(socket); socket = badSocket; }
        active = false;
    }
};
MmWaveReceiver::MmWaveReceiver(MmWaveReceiverConfig config, Reporter reporter)
    : impl_(std::make_unique<Impl>(std::move(config), std::move(reporter))) {}
MmWaveReceiver::~MmWaveReceiver() = default;
void MmWaveReceiver::start() { impl_->start(); }
void MmWaveReceiver::stop() noexcept { impl_->stop(); }
bool MmWaveReceiver::running() const noexcept { return impl_->active; }
std::uint16_t MmWaveReceiver::boundPort() const noexcept { return impl_->bound; }
}
