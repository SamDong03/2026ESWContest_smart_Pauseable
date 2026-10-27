part of '../guardian_home_page.dart';

class _RecordsTab extends StatelessWidget {
  const _RecordsTab({
    required this.doorEvents,
    required this.loadPhoto,
    required this.isConfirmed,
    required this.onDoorEventTap,
  });

  final List<DoorEvent> doorEvents;
  final Future<Uint8List> Function(DoorEvent) loadPhoto;
  final bool Function(DoorEvent event) isConfirmed;
  final ValueChanged<DoorEvent> onDoorEventTap;

  @override
  Widget build(BuildContext context) {
    return _TabFrame(
      title: '생활 이벤트 기록',
      subtitle: '서버에 저장된 출입 장면과 촬영 시각을 확인하세요.',
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
        if (doorEvents.isEmpty)
          const Card(
            child: ListTile(
              leading: Icon(Icons.photo_camera_outlined),
              title: Text('아직 저장된 출입 장면이 없어요'),
              subtitle: Text('새 출입 사진이 전송되면 이곳에서 확인할 수 있어요.'),
            ),
          ),
      ],
    );
  }
}
