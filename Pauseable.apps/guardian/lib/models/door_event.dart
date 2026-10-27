enum DoorEventDirection { exit, entry, unknown }

class DoorEvent {
  const DoorEvent({
    required this.id,
    required this.occurredAt,
    required this.timeLabel,
    required this.direction,
    required this.title,
    required this.description,
    required this.imageUrl,
    required this.isConfirmed,
    this.source = '',
  });

  final String id;
  final DateTime occurredAt;
  final String timeLabel;
  final DoorEventDirection direction;
  final String title;
  final String description;
  final String imageUrl;
  final bool isConfirmed;
  final String source;

  bool get isSample =>
      source == 'mock_camera' || imageUrl.startsWith('asset://');

  String get directionLabel => switch (direction) {
    DoorEventDirection.exit => '외출',
    DoorEventDirection.entry => '귀가',
    DoorEventDirection.unknown => '출입',
  };

  factory DoorEvent.fromJson(Map<String, dynamic> json) {
    return DoorEvent(
      id: json['id'] as String,
      occurredAt: DateTime.parse(json['occurred_at'] as String),
      timeLabel: json['time_label'] as String,
      direction: _doorEventDirectionFromJson(json['direction'] as String),
      title: json['title'] as String,
      description: json['description'] as String,
      imageUrl: json['image_url'] as String,
      isConfirmed: json['is_confirmed'] as bool? ?? false,
      source: json['source'] as String? ?? '',
    );
  }
}

DoorEventDirection _doorEventDirectionFromJson(String value) {
  return switch (value) {
    'exit' => DoorEventDirection.exit,
    'entry' => DoorEventDirection.entry,
    _ => DoorEventDirection.unknown,
  };
}
