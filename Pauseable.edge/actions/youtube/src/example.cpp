#include <alog.hpp>
#include "DBusObserver.hpp"

#include "example.h"


std::string convertPropertyValue(const sdbus::Variant& value) {
    std::variant<int64_t, double, bool, std::string, std::vector<std::string>, uint8_t> v = value;
    if (std::holds_alternative<int64_t>(v)) {
        return std::to_string(std::get<int64_t>(v));
    } else if (std::holds_alternative<double>(v)) {
        return std::to_string(std::get<double>(v));
    } else if (std::holds_alternative<bool>(v)) {
        return std::get<bool>(v) ? "true" : "false";
    } else if (std::holds_alternative<std::string>(v)) {
        return std::get<std::string>(v);
    } else if (std::holds_alternative<std::vector<std::string>>(v)) {
        std::string result = "[";
        bool first = true;
        for (const auto& str : std::get<std::vector<std::string>>(v)) {
            if (!first) {
                result += ", ";
            }
            first = false;
            result += str;
        }
        result += "]";
        return result;
    } else if (std::holds_alternative<uint8_t>(v)) {

        uint8_t type = std::get<uint8_t>(v);
        std::string err;
        switch(type) {
            case 1:
                err = "<NotFound>";
                break;
            case 2:
                err = "<NotAllowed>";
                break;
            case 3:
                err = "<NotPublic>";
                break;
            default:
                err = "<Unknown>";
                break;
        }
        return err;
    } else {
        return "<Unknown type>";
    }
}

PropertyManagerProxy::PropertyManagerProxy(sdbus::IProxy& proxy)
    : com::atlas::PropertyManager1_proxy(proxy)
    , proxy_(proxy)
{


    registerProxy();
}

void PropertyManagerProxy::onPropertyChanged(const std::string& id, const sdbus::Variant& value) {

    alog::logDebug("PROP_CHANGED", "Property changed: {} = {}", id, convertPropertyValue(value));
}


std::unique_ptr<DBusObserver<PropertyManagerProxy>> observer = nullptr;

void usePropertyManagerWithObserver(std::shared_ptr<sdbus::IConnection> connection) {


    observer = std::make_unique<DBusObserver<PropertyManagerProxy>>(
        connection,
        "com.atlas.PropertyManager1",
        "/com/atlas/PropertyManager1",


        [](PropertyManagerProxy* client) {

            alog::logInfo("PROP_PROXY", " - Service is available");

            try {
                auto result = client->Get("example.display.brightness");


                int64_t value = result.get<int64_t>();
                alog::logInfo("PROP_CURRENT", "Current value: {}", value);
            } catch (const std::exception& e) {
                alog::logError("PROP_GET_ERROR", "Exception: {}", e.what());
            }
        },
        [](PropertyManagerProxy* client) {

            alog::logInfo("PROP_PROXY", " - Service is unavailable");
        }
    );
}
