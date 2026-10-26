
#include <alog.hpp>

#include "DBusObserver.hpp"
#include "PropertyManagerClient.hpp"

#include <memory>
#include <string>
#include <variant>
#include <vector>

namespace {

std::string convertPropertyValue(const sdbus::Variant& value)
{
    std::variant<int64_t, double, bool, std::string, std::vector<std::string>, uint8_t> converted = value;
    if (std::holds_alternative<int64_t>(converted)) {
        return std::to_string(std::get<int64_t>(converted));
    }
    if (std::holds_alternative<double>(converted)) {
        return std::to_string(std::get<double>(converted));
    }
    if (std::holds_alternative<bool>(converted)) {
        return std::get<bool>(converted) ? "true" : "false";
    }
    if (std::holds_alternative<std::string>(converted)) {
        return std::get<std::string>(converted);
    }
    if (std::holds_alternative<std::vector<std::string>>(converted)) {
        std::string result = "[";
        bool first = true;
        for (const auto& item : std::get<std::vector<std::string>>(converted)) {
            if (!first) {
                result += ", ";
            }
            first = false;
            result += item;
        }
        result += "]";
        return result;
    }
    if (std::holds_alternative<uint8_t>(converted)) {
        switch (std::get<uint8_t>(converted)) {
            case 1: return "<NotFound>";
            case 2: return "<NotAllowed>";
            case 3: return "<NotPublic>";
            default: return "<Unknown>";
        }
    }
    return "<Unknown type>";
}


std::unique_ptr<DBusObserver<PropertyManagerProxy>> observer;

}

PropertyManagerProxy::PropertyManagerProxy(sdbus::IProxy& proxy)
    : com::atlas::PropertyManager1_proxy(proxy)
    , proxy_(proxy)
{
    registerProxy();
}

void PropertyManagerProxy::onPropertyChanged(const std::string& id, const sdbus::Variant& value)
{
    alog::logDebug("PROP_CHANGED", "Property changed: {} = {}", id, convertPropertyValue(value));
}

void usePropertyManagerWithObserver(std::shared_ptr<sdbus::IConnection> connection)
{
    observer = std::make_unique<DBusObserver<PropertyManagerProxy>>(
        connection,
        "com.atlas.PropertyManager1",
        "/com/atlas/PropertyManager1",
        [](PropertyManagerProxy* client) {
            alog::logInfo("PROP_PROXY", "Service is available");

            try {
                auto result = client->Get("example.display.brightness");
                const int64_t value = result.get<int64_t>();
                alog::logInfo("PROP_CURRENT", "Current value: {}", value);
            } catch (const std::exception& e) {
                alog::logError("PROP_GET_ERROR", "Exception: {}", e.what());
            }
        },
        [](PropertyManagerProxy*) {
            alog::logInfo("PROP_PROXY", "Service is unavailable");
        }
    );
}
