part of '../guardian_home_page.dart';

class _AlertsTab extends StatefulWidget {
  const _AlertsTab({
    required this.patientName,
    required this.alerts,
    required this.historyLoadFailed,
    required this.onRetryHistory,
    required this.anomalyPaused,
    required this.pausedDuration,
    required this.onConfirmNormal,
    required this.onResume,
    required this.onAlertTap,
  });

  final String patientName;
  final List<GuardianAlert> alerts;
  final bool historyLoadFailed;
  final VoidCallback onRetryHistory;
  final bool anomalyPaused;
  final String? pausedDuration;
  final VoidCallback onConfirmNormal;
  final VoidCallback onResume;
  final ValueChanged<GuardianAlert> onAlertTap;

  @override
  State<_AlertsTab> createState() => _AlertsTabState();
}

class _AlertsTabState extends State<_AlertsTab> {
  String _selectedFilter = '전체';

  @override
  Widget build(BuildContext context) {
    final visibleAlerts = _selectedFilter == '전체'
        ? widget.alerts
        : widget.alerts
              .where(
                (alert) => _selectedFilter == '미확인'
                    ? alert.isServerAlert && !alert.isRead
                    : alert.category == _selectedFilter,
              )
              .toList();
    final unreadCount = widget.alerts
        .where((alert) => alert.isServerAlert && !alert.isRead)
        .length;

    return _TabFrame(
      title: '알림 센터',
      subtitle: '${widget.patientName}의 최근 감지 내역 · 미확인 $unreadCount건',
      children: [
        if (widget.historyLoadFailed) ...[
          ListTile(
            title: const Text('지난 알림을 불러오지 못했습니다.'),
            subtitle: const Text('현재 화면에 보이는 알림만으로 안전 상태를 판단하지 마세요.'),
            trailing: TextButton(
              onPressed: widget.onRetryHistory,
              child: const Text('재시도'),
            ),
          ),
          const SizedBox(height: 12),
        ],
        Wrap(
          spacing: 8,
          children: ['전체', '미확인', '확인 필요']
              .map(
                (filter) => ChoiceChip(
                  label: Text(filter),
                  selected: _selectedFilter == filter,
                  onSelected: (_) => setState(() => _selectedFilter = filter),
                ),
              )
              .toList(),
        ),
        const SizedBox(height: 18),
        ...visibleAlerts.map(
          (alert) => Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: _NotificationCard(
              alert: alert,
              acknowledged: alert.isRepetitiveBehavior && widget.anomalyPaused,
              pausedDuration: alert.isRepetitiveBehavior
                  ? widget.pausedDuration
                  : null,
              onConfirmNormal: alert.isRepetitiveBehavior
                  ? widget.onConfirmNormal
                  : null,
              onResume: alert.isRepetitiveBehavior ? widget.onResume : null,
              onTap: () => widget.onAlertTap(alert),
            ),
          ),
        ),
      ],
    );
  }
}
