part of '../guardian_home_page.dart';

class _RecordsTab extends StatelessWidget {
  const _RecordsTab({
    required this.activity,
    required this.doorEvents,
    required this.loadPhoto,
    required this.isConfirmed,
    required this.onDoorEventTap,
    required this.onActivityEventTap,
  });

  final ActivitySummary activity;
  final List<DoorEvent> doorEvents;
  final Future<Uint8List> Function(DoorEvent) loadPhoto;
  final bool Function(DoorEvent event) isConfirmed;
  final ValueChanged<DoorEvent> onDoorEventTap;
  final ValueChanged<ActivityEvent> onActivityEventTap;

  @override
  Widget build(BuildContext context) {
    return _TabFrame(
      title: '생활 이벤트 기록',
      subtitle: '가전·현관 센서에서 수집된 이벤트를 확인하세요.',
      children: [
        if (doorEvents.isNotEmpty) ...[
          Text(
            '현관 출입 기록',
            style: TextStyle(
              color: _primaryText(context),
              fontSize: 18,
              fontWeight: FontWeight.w800,
            ),
          ),
          const SizedBox(height: 5),
          Text(
            '촬영된 장면과 외출 시간을 확인할 수 있어요.',
            style: TextStyle(color: _secondaryText(context), fontSize: 12),
          ),
          const SizedBox(height: 12),
          for (final event in doorEvents) ...[
            _DoorEventRecordCard(
              event: event,
              loadBytes: () => loadPhoto(event),
              confirmed: isConfirmed(event),
              onTap: () => onDoorEventTap(event),
            ),
            const SizedBox(height: 10),
          ],
        ],
        const SizedBox(height: 24),
        Text(
          '오늘의 센서 이벤트',
          style: TextStyle(
            color: _primaryText(context),
            fontSize: 18,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 12),
        Card(
          shape: const RoundedRectangleBorder(
            borderRadius: BorderRadius.all(Radius.circular(20)),
          ),
          child: Column(
            children: [
              for (var index = 0; index < activity.events.length; index++) ...[
                _TimelineTile(
                  time: activity.events[index].timeLabel,
                  title: activity.events[index].title,
                  icon: _activityIcon(activity.events[index].type),
                  onTap: () => onActivityEventTap(activity.events[index]),
                ),
                if (index < activity.events.length - 1)
                  const Divider(
                    height: 1,
                    indent: 68,
                    color: Color(0xFFE8ECEA),
                  ),
              ],
            ],
          ),
        ),
      ],
    );
  }
}
