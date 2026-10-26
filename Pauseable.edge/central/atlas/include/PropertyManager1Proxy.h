#ifndef PAUSEABLE_PROPERTY_MANAGER_1_PROXY_H
#define PAUSEABLE_PROPERTY_MANAGER_1_PROXY_H


#include <sdbus-c++/sdbus-c++.h>
#include <map>
#include <string>
#include <tuple>
#include <vector>

namespace com {
namespace atlas {

class PropertyManager1_proxy
{
public:
    static constexpr const char* INTERFACE_NAME = "com.atlas.PropertyManager1";

protected:
    explicit PropertyManager1_proxy(sdbus::IProxy& proxy)
        : m_proxy(proxy)
    {
    }

    PropertyManager1_proxy(const PropertyManager1_proxy&) = delete;
    PropertyManager1_proxy& operator=(const PropertyManager1_proxy&) = delete;
    PropertyManager1_proxy(PropertyManager1_proxy&&) = delete;
    PropertyManager1_proxy& operator=(PropertyManager1_proxy&&) = delete;

    ~PropertyManager1_proxy() = default;

    void registerProxy()
    {
        m_proxy.uponSignal("PropertyChanged").onInterface(INTERFACE_NAME).call(
            [this](const std::string& id, const sdbus::Variant& value) {
                this->onPropertyChanged(id, value);
            });
    }

    virtual void onPropertyChanged(const std::string& id, const sdbus::Variant& value)
    {
        (void)id;
        (void)value;
    }

public:
    sdbus::Variant Get(const std::string& id)
    {
        sdbus::Variant result;
        m_proxy.callMethod("Get").onInterface(INTERFACE_NAME).withArguments(id).storeResultsTo(result);
        return result;
    }

    bool Set(const std::string& id, const sdbus::Variant& value)
    {
        bool result;
        m_proxy.callMethod("Set").onInterface(INTERFACE_NAME).withArguments(id, value).storeResultsTo(result);
        return result;
    }

    std::map<std::string, sdbus::Variant> GetProperties(const std::vector<std::string>& ids)
    {
        std::map<std::string, sdbus::Variant> result;
        m_proxy.callMethod("GetProperties").onInterface(INTERFACE_NAME).withArguments(ids).storeResultsTo(result);
        return result;
    }

    std::tuple<bool, std::vector<sdbus::Variant>> GetAllowedValues(const std::string& id)
    {
        std::tuple<bool, std::vector<sdbus::Variant>> result;
        m_proxy.callMethod("GetAllowedValues").onInterface(INTERFACE_NAME).withArguments(id).storeResultsTo(result);
        return result;
    }

private:
    sdbus::IProxy& m_proxy;
};

}
}

#endif
