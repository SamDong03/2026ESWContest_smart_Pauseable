

function value(key,    i, prefix) {
    prefix = key "="
    for (i = 1; i <= NF; i++)
        if (index($i, prefix) == 1) return substr($i, length(prefix) + 1)
    return ""
}
function valid_id(id) {
    return length(id) > 0 && length(id) <= 160 && id ~ /^[A-Za-z0-9][A-Za-z0-9._:-]*$/
}
/CENTRAL_DECISION_ACCEPTED[[:space:]]/ {

    if (++accepted_count > 1024) {
        for (key in accepted) delete accepted[key]
        accepted_count = 1
    }
    id = value("event_id")
    if (valid_id(id) && value("source") == "wandering-ai" &&
        value("decision") == "wandering_suspected" &&
        (value("risk") == "caution" || value("risk") == "danger"))
        accepted[id] = 1
    else delete accepted[id]
    next
}
/CENTRAL_ACTION_ROUTED[[:space:]]/ {
    id = value("event_id")
    if (accepted[id] && value("disposition") == "execute" && value("speak") == "true") {
        print id
        fflush()
    }
    delete accepted[id]
}
