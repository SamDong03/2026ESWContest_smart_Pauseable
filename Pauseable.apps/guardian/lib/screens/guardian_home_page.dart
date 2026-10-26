import 'dart:async';
import 'dart:typed_data';

import 'package:flutter/material.dart';

import '../models/activity_summary.dart';
import '../models/demo_scenario.dart';
import '../models/door_event.dart';
import '../models/guardian_alert.dart';
import '../models/guardian_snapshot.dart';
import '../models/guardian_support.dart';
import '../models/home_environment.dart';
import '../models/live_app_alert.dart';
import '../models/patient_status.dart';
import '../models/voice_training_progress.dart';
import '../models/voice_training_prompt.dart';
import '../models/voice_consent_receipt.dart';
import '../repositories/guardian_repository.dart';
import '../services/live_alert_client.dart';
import '../services/native_push_client.dart';
import '../services/web_push_client.dart';
import '../services/voice_recording_service.dart';
import '../services/voice_training_script_loader.dart';
import 'home_region_page.dart';
import 'favorite_songs_page.dart';
import 'voice_recording_consent_sheet.dart';

part 'tabs/alerts_tab.dart';
part 'tabs/records_tab.dart';
part 'tabs/settings_tab.dart';
part 'tabs/home_tab.dart';
part 'widgets/guardian_widgets.dart';
part 'widgets/door_photo_viewer.dart';
part 'widgets/voice_recording_sheet.dart';
part 'widgets/care_profile_dialog.dart';

const _green = Color(0xFF356B5A);
const _dark = Color(0xFF18332B);
const _muted = Color(0xFF66756F);

Color _primaryText(BuildContext context) =>
    Theme.of(context).colorScheme.onSurface;

Color _secondaryText(BuildContext context) =>
    Theme.of(context).colorScheme.onSurfaceVariant;

Color _surfaceColor(BuildContext context) =>
    Theme.of(context).colorScheme.surface;

Color _softSurface(BuildContext context) =>
    Theme.of(context).colorScheme.surfaceContainerHighest;

IconData _alertIcon(GuardianAlertType type) => switch (type) {
  GuardianAlertType.repetitiveBehavior => Icons.door_front_door_outlined,
  GuardianAlertType.wandering => Icons.directions_walk_rounded,
  GuardianAlertType.inactivity => Icons.motion_photos_off_outlined,
  GuardianAlertType.medication => Icons.medication_outlined,
  GuardianAlertType.nightMovement => Icons.nights_stay_outlined,
  GuardianAlertType.appliance => Icons.home_outlined,
  GuardianAlertType.doorEvent => Icons.camera_alt_outlined,
};

Color _alertColor(GuardianAlertType type) => switch (type) {
  GuardianAlertType.repetitiveBehavior => const Color(0xFFB56A24),
  GuardianAlertType.wandering => const Color(0xFFC24B4B),
  GuardianAlertType.inactivity => const Color(0xFFC24B4B),
  GuardianAlertType.medication => const Color(0xFF4C6B9C),
  GuardianAlertType.nightMovement => const Color(0xFF6A55A3),
  GuardianAlertType.appliance => const Color(0xFF356B5A),
  GuardianAlertType.doorEvent => const Color(0xFF356B5A),
};

Color _alertBackground(GuardianAlertType type) => switch (type) {
  GuardianAlertType.repetitiveBehavior => const Color(0xFFFFEEDB),
  GuardianAlertType.wandering => const Color(0xFFFFE8E8),
  GuardianAlertType.inactivity => const Color(0xFFFFE8E8),
  GuardianAlertType.medication => const Color(0xFFE8EFFA),
  GuardianAlertType.nightMovement => const Color(0xFFF0EBFA),
  GuardianAlertType.appliance => const Color(0xFFE5F2ED),
  GuardianAlertType.doorEvent => const Color(0xFFE5F2ED),
};

IconData _activityIcon(ActivityEventType type) => switch (type) {
  ActivityEventType.light => Icons.lightbulb_outline_rounded,
  ActivityEventType.refrigerator => Icons.kitchen_outlined,
  ActivityEventType.television => Icons.tv_outlined,
  ActivityEventType.doorway => Icons.door_front_door_outlined,
};

class GuardianHomePage extends StatefulWidget {
  const GuardianHomePage({
    super.key,
    required this.repository,
    this.liveAlertClient,
    this.webPushClient,
    this.nativePushClient,
    required this.themeMode,
    required this.onThemeModeChanged,
    this.voiceRecorderFactory,
    required this.homeEnvironment,
    required this.onHomeEnvironmentChanged,
  });

  final GuardianRepository repository;
  final LiveAlertClient? liveAlertClient;
  final WebPushClient? webPushClient;
  final NativePushClient? nativePushClient;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onThemeModeChanged;
  final VoiceRecorderFactory? voiceRecorderFactory;
  final HomeEnvironment? homeEnvironment;
  final ValueChanged<HomeEnvironment> onHomeEnvironmentChanged;

  @override
  State<GuardianHomePage> createState() => _GuardianHomePageState();
}

class _GuardianHomePageState extends State<GuardianHomePage> {

  final Map<String, Future<Uint8List>> _doorPhotoRequests = {};

  Future<Uint8List> _loadDoorPhoto(DoorEvent event) async {
    final existing = _doorPhotoRequests[event.id];
    if (existing != null) return existing;
    if (_doorPhotoRequests.length >= 8) {
      _doorPhotoRequests.remove(_doorPhotoRequests.keys.first);
    }
    final request = widget.repository.loadDoorPhoto(eventId: event.id);
    _doorPhotoRequests[event.id] = request;
    try {
      return await request;
    } catch (_) {
      if (identical(_doorPhotoRequests[event.id], request)) {
        _doorPhotoRequests.remove(event.id);
      }
      rethrow;
    }
  }

  int _selectedIndex = Uri.base.queryParameters['tab'] == 'alerts' ? 1 : 0;
  String? _pausedAnomalyDuration;
  GuardianSnapshot? _snapshot;
  GuardianProfile? _guardianProfile;
  GuardianPreferences? _notificationPreferences;
  int _preferencesRevision = 0;

  void _preferencesChanged(GuardianPreferences preferences) {
    _notificationPreferences = preferences;
    _preferencesRevision++;
  }

  bool _loadingProfile = true;
  bool _profileLoadFailed = false;
  Object? _loadError;
  Object? _alertHistoryError;
  final Map<String, LiveAppAlert> _serverAlerts = {};
  final Set<String> _locallyReadAlertIds = {};
  VoiceTrainingProgress? _voiceTrainingProgress;
  Object? _voiceTrainingLoadError;
  DemoScenario? _applyingDemoScenario;
  final Set<String> _confirmedDoorEventIds = {};
  StreamSubscription<LiveAppAlert>? _liveAlertSubscription;
  StreamSubscription<LiveAlertConnectionStatus>? _liveStatusSubscription;
  StreamSubscription<void>? _nativeOpenSubscription;
  LiveAlertConnectionStatus _liveAlertStatus =
      LiveAlertConnectionStatus.stopped;

  @override
  void initState() {
    super.initState();
    _loadSnapshot();
    _loadGuardianProfile();
    _loadVoiceTrainingProgress();
    _bindLiveAlertClient();
    _bindNativePushClient();
  }

  void _bindNativePushClient() {
    final client = widget.nativePushClient;
    if (client == null) return;
    _nativeOpenSubscription = client.notificationOpens.listen((_) {
      if (client.consumeNotificationOpen()) _openNotificationHistory();
    });
    if (client.consumeNotificationOpen()) {
      WidgetsBinding.instance.addPostFrameCallback((_) {
        _openNotificationHistory();
      });
    }
  }

  void _openNotificationHistory() {
    if (!mounted) return;
    _selectTab(1);
    unawaited(_loadAlertHistory());
    unawaited(_loadSnapshot());
  }

  void _bindLiveAlertClient() {
    final client = widget.liveAlertClient;
    if (client == null) return;

    _liveAlertStatus = LiveAlertConnectionStatus.connecting;
    _liveAlertSubscription = client.alerts.listen(_handleLiveAlert);
    _liveStatusSubscription = client.statuses.listen((status) {
      if (mounted) setState(() => _liveAlertStatus = status);
      if (status == LiveAlertConnectionStatus.connected) {
        unawaited(_loadSnapshot());
      }
    });
    client.start();
  }

  void _handleLiveAlert(LiveAppAlert liveAlert) {
    if (!mounted) return;
    if (liveAlert.alertType == 'door_event') {
      unawaited(_loadSnapshot());
    }
    if (_serverAlerts.containsKey(liveAlert.id)) return;
    final alert = liveAlert.toGuardianAlert();
    setState(() {
      _serverAlerts[liveAlert.id] = liveAlert;
      _mergeServerAlerts();
    });
    unawaited(_showLiveAlertNotification(alert));
  }

  Future<void> _showLiveAlertNotification(GuardianAlert alert) async {
    final revision = _preferencesRevision;
    try {
      final preferences = await widget.repository.loadPreferences();
      if (!mounted) return;

      if (revision == _preferencesRevision) _preferencesChanged(preferences);
    } catch (_) {

    }
    if (!mounted || _notificationPreferences?.safetyNotifications == false) {
      return;
    }
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('새 실시간 알림 · ${alert.title}'),
        action: SnackBarAction(label: '보기', onPressed: () => _selectTab(1)),
      ),
    );
  }

  @override
  void didUpdateWidget(covariant GuardianHomePage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.nativePushClient, widget.nativePushClient)) {
      unawaited(_nativeOpenSubscription?.cancel() ?? Future<void>.value());
      _nativeOpenSubscription = null;
      _bindNativePushClient();
    }
    if (identical(oldWidget.liveAlertClient, widget.liveAlertClient)) return;
    unawaited(_liveAlertSubscription?.cancel() ?? Future<void>.value());
    unawaited(_liveStatusSubscription?.cancel() ?? Future<void>.value());
    _liveAlertSubscription = null;
    _liveStatusSubscription = null;
    _liveAlertStatus = LiveAlertConnectionStatus.stopped;
    _bindLiveAlertClient();
  }

  @override
  void dispose() {
    unawaited(_nativeOpenSubscription?.cancel() ?? Future<void>.value());
    unawaited(_liveAlertSubscription?.cancel() ?? Future<void>.value());
    unawaited(_liveStatusSubscription?.cancel() ?? Future<void>.value());
    super.dispose();
  }

  Future<void> _loadSnapshot() async {
    try {
      final snapshot = await widget.repository.loadSnapshot();
      if (!mounted) return;
      setState(() {
        _snapshot = snapshot;
        _mergeServerAlerts();
        _loadError = null;
      });
      unawaited(_loadAlertHistory());
    } catch (error) {
      if (!mounted) return;
      setState(() => _loadError = error);
    }
  }

  Future<void> _loadGuardianProfile() async {
    setState(() {
      _loadingProfile = true;
      _profileLoadFailed = false;
    });
    try {
      final profile = await widget.repository.loadGuardianProfile();
      if (mounted) setState(() => _guardianProfile = profile);
    } catch (_) {
      if (mounted) setState(() => _profileLoadFailed = true);
    } finally {
      if (mounted) setState(() => _loadingProfile = false);
    }
  }

  Future<void> _editGuardianProfile() async {
    if (_loadingProfile || _profileLoadFailed) return;
    final updated = await showDialog<GuardianProfile>(
      context: context,
      barrierDismissible: false,
      builder: (_) => _CareProfileDialog(
        repository: widget.repository,
        initial: _guardianProfile,
      ),
    );
    if (updated == null || !mounted) return;
    setState(() => _guardianProfile = updated);
    ScaffoldMessenger.of(context)
        .showSnackBar(const SnackBar(content: Text('보호자와 대상자 정보를 저장했습니다.')));
  }

  void _mergeServerAlerts() {
    final snapshot = _snapshot;
    if (snapshot == null) return;
    final recent = _serverAlerts.values.toList()
      ..sort((a, b) => b.occurredAt.compareTo(a.occurredAt));
    _snapshot = GuardianSnapshot(
      patient: snapshot.patient,
      alerts: List.unmodifiable([
        ...recent.map((alert) => alert.toGuardianAlert()),
        ...snapshot.alerts.where((alert) => !alert.isServerAlert),
      ]),
      activity: snapshot.activity,
      doorEvents: snapshot.doorEvents,
      demoScenario: snapshot.demoScenario,
    );
  }

  Future<void> _loadAlertHistory() async {
    try {
      final history = await widget.repository.loadAlertHistory();
      if (!mounted) return;
      setState(() {
        for (final alert in history) {
          _serverAlerts[alert.id] = _locallyReadAlertIds.contains(alert.id)
              ? alert.copyWith(isRead: true)
              : alert;
        }
        _alertHistoryError = null;
        _mergeServerAlerts();
      });
    } catch (error) {
      if (mounted) setState(() => _alertHistoryError = error);
    }
  }

  Future<void> _markAlertRead(String alertId) async {
    try {
      await widget.repository.markAlertRead(alertId);
      if (!mounted) return;
      setState(() {
        _locallyReadAlertIds.add(alertId);
        final alert = _serverAlerts[alertId];
        if (alert != null) {
          _serverAlerts[alertId] = alert.copyWith(isRead: true);
        }
        _mergeServerAlerts();
      });
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('알림 확인 상태를 저장하지 못했습니다. 다시 시도해 주세요.')),
      );
    }
  }

  Future<void> _loadVoiceTrainingProgress() async {
    try {
      final progress = await widget.repository.loadVoiceTrainingProgress();
      if (!mounted) return;
      setState(() {
        _voiceTrainingProgress = progress;
        _voiceTrainingLoadError = null;
      });
    } catch (error) {
      if (!mounted) return;
      setState(() => _voiceTrainingLoadError = error);
    }
  }

  void _selectTab(int index) {
    if (index == _selectedIndex) return;
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    setState(() => _selectedIndex = index);
  }

  Future<void> _activateDemoScenario(DemoScenario scenario) async {
    if (_applyingDemoScenario != null) return;
    setState(() => _applyingDemoScenario = scenario);

    try {
      await widget.repository.activateDemoScenario(scenarioId: scenario.id);
      final snapshot = await widget.repository.loadSnapshot();
      if (!mounted) return;
      setState(() {
        _snapshot = snapshot;
        _mergeServerAlerts();
        _loadError = null;
        _pausedAnomalyDuration = null;
        _confirmedDoorEventIds.clear();
      });
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('${scenario.label} 시나리오를 적용했습니다.')),
      );
    } catch (error) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('가짜 상황을 적용하지 못했습니다. 다시 시도해 주세요.')),
      );
    } finally {
      if (mounted) setState(() => _applyingDemoScenario = null);
    }
  }

  Future<void> _refreshSnapshot() async {
    await _loadSnapshot();
    if (!mounted || _loadError != null) return;
    ScaffoldMessenger.of(
      context,
    ).showSnackBar(const SnackBar(content: Text('가상 센서 데이터를 최신 상태로 갱신했습니다.')));
  }

  Future<void> _showAlertDetail(GuardianAlert alert) async {
    if (alert.isServerAlert && !alert.isRead) {
      unawaited(_markAlertRead(alert.id));
    }
    if (alert.type == GuardianAlertType.doorEvent &&
        alert.relatedEventId != null) {
      var event = _relatedDoorEvent(alert.relatedEventId!);
      if (event == null) {
        await _loadSnapshot();
        if (!mounted) return;
        event = _relatedDoorEvent(alert.relatedEventId!);
      }
      if (event != null) {
        await _showDoorEventDetail(event);
        return;
      }
    }
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Row(
                children: [
                  CircleAvatar(
                    backgroundColor: _alertBackground(alert.type),
                    foregroundColor: _alertColor(alert.type),
                    child: Icon(_alertIcon(alert.type)),
                  ),
                  const SizedBox(width: 12),
                  Expanded(
                    child: Text(
                      alert.title,
                      style: TextStyle(
                        color: _primaryText(sheetContext),
                        fontSize: 21,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 16),
              _detailRow(sheetContext, '감지 시각', alert.timeLabel),
              _detailRow(sheetContext, '상태', alert.category),
              if (alert.deviceId != null)
                _detailRow(sheetContext, '감지 기기', alert.deviceId!),
              if (alert.currentCount != null)
                _detailRow(
                  sheetContext,
                  '감지 횟수',
                  [
                    '${alert.currentCount}회',
                    if (alert.normalMin != null && alert.normalMax != null)
                      '평소 ${alert.normalMin}~${alert.normalMax}회',
                  ].join(' · '),
                ),
              const SizedBox(height: 12),
              Text(
                alert.description,
                style: TextStyle(
                  color: _secondaryText(sheetContext),
                  height: 1.5,
                ),
              ),
              const SizedBox(height: 20),
              SizedBox(
                width: double.infinity,
                child: alert.isRepetitiveBehavior && !alert.isServerAlert
                    ? FilledButton.icon(
                        onPressed: () {
                          Navigator.pop(sheetContext);
                          _showAnomalyPauseSheet(context);
                        },
                        icon: const Icon(Icons.check_circle_outline_rounded),
                        label: const Text('정상 상황으로 확인'),
                      )
                    : FilledButton(
                        onPressed: () => Navigator.pop(sheetContext),
                        child: const Text('확인했습니다'),
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _detailRow(BuildContext context, String label, String value) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 9),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          SizedBox(
            width: 78,
            child: Text(
              label,
              style: TextStyle(color: _secondaryText(context), fontSize: 12),
            ),
          ),
          Expanded(
            child: Text(
              value,
              style: TextStyle(
                color: _primaryText(context),
                fontWeight: FontWeight.w700,
              ),
            ),
          ),
        ],
      ),
    );
  }

  Future<void> _showActivityEventDetail(ActivityEvent event) async {
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              CircleAvatar(
                backgroundColor: const Color(0xFFE5F1EC),
                foregroundColor: _green,
                child: Icon(_activityIcon(event.type)),
              ),
              const SizedBox(height: 14),
              Text(
                event.title,
                style: TextStyle(
                  color: _primaryText(sheetContext),
                  fontSize: 21,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 16),
              _detailRow(sheetContext, '발생 시각', event.timeLabel),
              _detailRow(sheetContext, '센서 상태', event.state.name),
              _detailRow(
                sheetContext,
                '원본 시각',
                event.occurredAt.toIso8601String(),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: FilledButton(
                  onPressed: () => Navigator.pop(sheetContext),
                  child: const Text('확인'),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Future<void> _requestCareCall() async {
    final confirmed = await _confirmAction(
      title: '보호 전화를 연결할까요?',
      message: '${_snapshot!.patient.name} 님에게 보호 전화 연결 요청을 보냅니다.',
      confirmLabel: '전화 요청',
    );
    if (!confirmed || !mounted) return;
    await _runAction(widget.repository.requestCareCall);
  }

  Future<void> _requestEmergencyContact() async {
    final confirmed = await _confirmAction(
      title: '긴급 연락을 요청할까요?',
      message: '등록된 긴급 연락망에 즉시 요청을 보냅니다. 현재는 가상 동작입니다.',
      confirmLabel: '긴급 요청',
      destructive: true,
    );
    if (!confirmed || !mounted) return;
    await _runAction(widget.repository.requestEmergencyContact);
  }

  Future<bool> _confirmAction({
    required String title,
    required String message,
    required String confirmLabel,
    bool destructive = false,
  }) async {
    return await showDialog<bool>(
          context: context,
          builder: (dialogContext) => AlertDialog(
            title: Text(title),
            content: Text(message),
            actions: [
              TextButton(
                onPressed: () => Navigator.pop(dialogContext, false),
                child: const Text('취소'),
              ),
              FilledButton(
                style: destructive
                    ? FilledButton.styleFrom(
                        backgroundColor: const Color(0xFFB53E3E),
                      )
                    : null,
                onPressed: () => Navigator.pop(dialogContext, true),
                child: Text(confirmLabel),
              ),
            ],
          ),
        ) ??
        false;
  }

  Future<void> _runAction(
    Future<GuardianActionResult> Function() action,
  ) async {
    try {
      final result = await action();
      if (!mounted) return;
      await showDialog<void>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          icon: const Icon(Icons.check_circle_rounded, color: _green, size: 42),
          title: Text(result.title),
          content: Text('${result.message}\n\n요청 번호: ${result.referenceId}'),
          actions: [
            FilledButton(
              onPressed: () => Navigator.pop(dialogContext),
              child: const Text('확인'),
            ),
          ],
        ),
      );
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('요청을 처리하지 못했습니다. 다시 시도해 주세요.')),
      );
    }
  }

  Future<void> _showVoiceRecordingSheet(BuildContext context) async {
    final receipt = await showModalBottomSheet<VoiceConsentReceipt>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (_) => VoiceRecordingConsentSheet(repository: widget.repository),
    );
    if (receipt == null || !context.mounted) return;

    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      isDismissible: false,
      enableDrag: false,
      builder: (sheetContext) => _VoiceRecordingSheet(
        repository: widget.repository,
        hasVoiceConsent: true,
        recorderFactory:
            widget.voiceRecorderFactory ?? createDeviceVoiceRecorder,
      ),
    );

    if (mounted) await _loadVoiceTrainingProgress();
  }

  Future<void> _showAnomalyPauseSheet(BuildContext context) async {
    final duration = await showModalBottomSheet<String>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: Padding(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                '정상 상황으로 확인할까요?',
                style: TextStyle(
                  color: _primaryText(sheetContext),
                  fontSize: 21,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '현관문 반복 행동 알림만 선택한 시간 동안 멈춥니다. 낙상·화재·가스·SOS 등 긴급 알림은 계속 작동합니다.',
                style: TextStyle(
                  color: _secondaryText(sheetContext),
                  height: 1.45,
                ),
              ),
              const SizedBox(height: 18),
              ...['30분', '1시간', '3시간', '오늘 하루'].map(
                (label) => ListTile(
                  contentPadding: EdgeInsets.zero,
                  leading: const CircleAvatar(
                    backgroundColor: Color(0xFFE5F1EC),
                    foregroundColor: _green,
                    child: Icon(Icons.schedule_rounded),
                  ),
                  title: Text(
                    '$label 동안 알림 중지',
                    style: const TextStyle(fontWeight: FontWeight.w700),
                  ),
                  trailing: const Icon(Icons.chevron_right_rounded),
                  onTap: () => Navigator.pop(sheetContext, label),
                ),
              ),
            ],
          ),
        ),
      ),
    );

    if (duration == null || !context.mounted) return;

    try {
      await widget.repository.pauseAlert(
        alertId: _snapshot!.repetitiveBehaviorAlert.id,
        duration: _durationForLabel(duration),
      );
      if (!context.mounted) return;
      setState(() => _pausedAnomalyDuration = duration);
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('현관문 반복 행동 알림을 $duration 동안 중지했습니다.')),
      );
    } catch (_) {
      if (!context.mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('알림 중지 요청에 실패했습니다. 다시 시도해 주세요.')),
      );
    }
  }

  Duration _durationForLabel(String label) {
    return switch (label) {
      '30분' => const Duration(minutes: 30),
      '1시간' => const Duration(hours: 1),
      '3시간' => const Duration(hours: 3),
      _ => const Duration(days: 1),
    };
  }

  Future<void> _resumeAnomalyAlerts() async {
    try {
      await widget.repository.resumeAlert(
        alertId: _snapshot!.repetitiveBehaviorAlert.id,
      );
      if (!mounted) return;
      setState(() => _pausedAnomalyDuration = null);
      ScaffoldMessenger.of(
        context,
      ).showSnackBar(const SnackBar(content: Text('현관문 반복 행동 알림을 다시 켰습니다.')));
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('알림 재활성화에 실패했습니다. 다시 시도해 주세요.')),
      );
    }
  }

  bool _isDoorEventConfirmed(DoorEvent event) {
    return event.isConfirmed || _confirmedDoorEventIds.contains(event.id);
  }

  Future<void> _confirmDoorEvent(DoorEvent event) async {
    try {
      await widget.repository.confirmDoorEvent(eventId: event.id);
      if (!mounted) return;
      setState(() => _confirmedDoorEventIds.add(event.id));
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('출입 장면을 확인 완료로 표시했습니다.')));
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('출입 장면 확인 요청에 실패했습니다. 다시 시도해 주세요.')),
      );
    }
  }

  DoorEvent? _relatedDoorEvent(String eventId) {
    for (final event in _snapshot?.doorEvents ?? const <DoorEvent>[]) {
      if (event.id == eventId) return event;
    }
    return null;
  }

  Future<void> _showDoorEventDetail(DoorEvent event) async {
    final confirmed = _isDoorEventConfirmed(event);
    await showModalBottomSheet<void>(
      context: context,
      showDragHandle: true,
      isScrollControlled: true,
      builder: (sheetContext) => SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              ClipRRect(
                borderRadius: BorderRadius.circular(20),
                child: _DoorEventImage(
                  imageUrl: event.imageUrl,
                  loadBytes: () => _loadDoorPhoto(event),
                  semanticLabel: '${event.directionLabel} 당시 현관 장면',
                  naturalHeight: true,
                ),
              ),
              const SizedBox(height: 8),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: () => Navigator.of(sheetContext).push<void>(
                    MaterialPageRoute(
                      builder: (_) => _DoorPhotoViewerPage(
                        event: event,
                        loadBytes: () => _loadDoorPhoto(event),
                      ),
                    ),
                  ),
                  icon: const Icon(Icons.zoom_in_rounded),
                  label: const Text('사진 크게 보기 · 확대'),
                ),
              ),
              const SizedBox(height: 18),
              Row(
                children: [
                  Container(
                    padding: const EdgeInsets.symmetric(
                      horizontal: 10,
                      vertical: 6,
                    ),
                    decoration: BoxDecoration(
                      color: const Color(0xFFE5F1EC),
                      borderRadius: BorderRadius.circular(20),
                    ),
                    child: Text(
                      event.directionLabel,
                      style: const TextStyle(
                        color: _green,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                  ),
                  const Spacer(),
                  Text(
                    event.timeLabel,
                    style: TextStyle(
                      color: _secondaryText(sheetContext),
                      fontSize: 12,
                    ),
                  ),
                ],
              ),
              const SizedBox(height: 12),
              Text(
                event.title,
                style: TextStyle(
                  color: _primaryText(sheetContext),
                  fontSize: 22,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 7),
              Text(
                event.description,
                style: TextStyle(
                  color: _secondaryText(sheetContext),
                  height: 1.45,
                ),
              ),
              const SizedBox(height: 16),
              SizedBox(
                width: double.infinity,
                child: confirmed
                    ? OutlinedButton.icon(
                        onPressed: () => Navigator.pop(sheetContext),
                        icon: const Icon(Icons.verified_outlined),
                        label: const Text('보호자 확인 완료 · 닫기'),
                      )
                    : FilledButton.icon(
                        onPressed: () {
                          Navigator.pop(sheetContext);
                          _confirmDoorEvent(event);
                        },
                        icon: const Icon(Icons.check_circle_outline_rounded),
                        label: const Text('이 장면 확인 완료'),
                      ),
              ),
              if (event.imageUrl.startsWith('asset://')) ...[
                const SizedBox(height: 10),
                const Text(
                  '샘플 사진입니다.',
                  style: TextStyle(color: Color(0xFF80908A), fontSize: 11),
                ),
              ],
            ],
          ),
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final snapshot = _snapshot;
    if (snapshot == null) {
      return Scaffold(
        body: Center(
          child: _loadError == null
              ? const CircularProgressIndicator()
              : Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Text('보호자 정보를 불러오지 못했습니다.'),
                    const SizedBox(height: 12),
                    FilledButton(
                      onPressed: _loadSnapshot,
                      child: const Text('다시 시도'),
                    ),
                  ],
                ),
        ),
      );
    }

    return Scaffold(
      body: IndexedStack(
        index: _selectedIndex,
        children: [
          _buildHomeTab(context, snapshot),
          _AlertsTab(
            patientName: _guardianProfile?.patientLabel ?? '돌봄 대상자',
            alerts: snapshot.alerts,
            historyLoadFailed: _alertHistoryError != null,
            onRetryHistory: () => unawaited(_loadAlertHistory()),
            anomalyPaused: _pausedAnomalyDuration != null,
            pausedDuration: _pausedAnomalyDuration,
            onConfirmNormal: () => _showAnomalyPauseSheet(context),
            onResume: () => _resumeAnomalyAlerts(),
            onAlertTap: _showAlertDetail,
          ),
          _RecordsTab(
            activity: snapshot.activity,
            doorEvents: snapshot.doorEvents,
            loadPhoto: _loadDoorPhoto,
            isConfirmed: _isDoorEventConfirmed,
            onDoorEventTap: _showDoorEventDetail,
            onActivityEventTap: _showActivityEventDetail,
          ),
          _SettingsTab(
            repository: widget.repository,
            onPreferencesChanged: _preferencesChanged,
            webPushClient: widget.webPushClient,
            nativePushClient: widget.nativePushClient,
            homeEnvironment: widget.homeEnvironment,
            onHomeEnvironmentChanged: widget.onHomeEnvironmentChanged,
            profile: _guardianProfile,
            loadingProfile: _loadingProfile,
            profileLoadFailed: _profileLoadFailed,
            onEditProfile: _editGuardianProfile,
            onRetryProfile: _loadGuardianProfile,
            activeScenario: snapshot.demoScenario,
            applyingScenario: _applyingDemoScenario,
            onScenarioSelected: _activateDemoScenario,
            themeMode: widget.themeMode,
            onThemeModeChanged: widget.onThemeModeChanged,
          ),
        ],
      ),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _selectedIndex,
        onDestinationSelected: _selectTab,
        destinations: const [
          NavigationDestination(
            icon: Icon(Icons.home_outlined),
            selectedIcon: Icon(Icons.home_rounded),
            label: '홈',
          ),
          NavigationDestination(
            icon: Icon(Icons.notifications_none_rounded),
            selectedIcon: Icon(Icons.notifications_rounded),
            label: '알림',
          ),
          NavigationDestination(icon: Icon(Icons.history_rounded), label: '기록'),
          NavigationDestination(
            icon: Icon(Icons.settings_outlined),
            selectedIcon: Icon(Icons.settings_rounded),
            label: '설정',
          ),
        ],
      ),
    );
  }
}
