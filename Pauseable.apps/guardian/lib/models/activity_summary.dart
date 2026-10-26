enum ActivityEventType { light, refrigerator, television, doorway }

enum ActivityEventState { on, off, open, closed }

class ActivityEvent {
  const ActivityEvent({
    required this.occurredAt,
    required this.timeLabel,
    required this.title,
    required this.type,
    required this.state,
  });

  final DateTime occurredAt;
  final String timeLabel;
  final String title;
  final ActivityEventType type;
  final ActivityEventState state;

  factory ActivityEvent.fromJson(Map<String, dynamic> json) {
    return ActivityEvent(
      occurredAt: DateTime.parse(json['occurred_at'] as String),
      timeLabel: json['time_label'] as String,
      title: json['title'] as String,
      type: _activityEventTypeFromJson(json['type'] as String),
      state: _activityEventStateFromJson(json['state'] as String),
    );
  }
}

ActivityEventState _activityEventStateFromJson(String value) {
  return switch (value) {
    'on' => ActivityEventState.on,
    'off' => ActivityEventState.off,
    'open' => ActivityEventState.open,
    'closed' => ActivityEventState.closed,
    _ => throw FormatException('Unknown activity event state: $value'),
  };
}

class ActivitySummary {
  const ActivitySummary({required this.events});

  final List<ActivityEvent> events;

  factory ActivitySummary.fromJson(Map<String, dynamic> json) {
    final events = json['events'] as List<dynamic>;

    return ActivitySummary(
      events: List.unmodifiable(
        events.map(
          (event) => ActivityEvent.fromJson(event as Map<String, dynamic>),
        ),
      ),
    );
  }
}

ActivityEventType _activityEventTypeFromJson(String value) {
  return switch (value) {
    'light' => ActivityEventType.light,
    'refrigerator' => ActivityEventType.refrigerator,
    'television' => ActivityEventType.television,
    'doorway' => ActivityEventType.doorway,
    _ => throw FormatException('Unknown activity event type: $value'),
  };
}
