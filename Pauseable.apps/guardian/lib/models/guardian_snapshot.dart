import 'activity_summary.dart';
import 'demo_scenario.dart';
import 'door_event.dart';
import 'guardian_alert.dart';
import 'patient_status.dart';

class GuardianSnapshot {
  const GuardianSnapshot({
    required this.patient,
    required this.alerts,
    required this.activity,
    required this.doorEvents,
    required this.demoScenario,
    this.repetitiveAlertPauseUntil,
    this.repetitiveAlertPauseAvailable = false,
  });

  final PatientStatus patient;
  final List<GuardianAlert> alerts;
  final ActivitySummary activity;
  final List<DoorEvent> doorEvents;
  final DemoScenario demoScenario;
  final DateTime? repetitiveAlertPauseUntil;
  final bool repetitiveAlertPauseAvailable;

  bool get repetitiveAlertsPaused =>
      repetitiveAlertPauseAvailable &&
      (repetitiveAlertPauseUntil?.isAfter(DateTime.now()) ?? false);

  factory GuardianSnapshot.fromJson(Map<String, dynamic> json) {
    final alerts = json['alerts'] as List<dynamic>;
    final doorEvents = json['door_events'] as List<dynamic>? ?? const [];
    final pause = json['repetitive_alert_pause'] as Map<String, dynamic>?;
    final until = pause?['paused_until'] is String
        ? DateTime.tryParse(pause!['paused_until'] as String)
        : null;
    final available =
        pause?['available'] == true &&
        pause?['scope'] == 'repetitive_behavior' &&
        (pause?['is_paused'] != true || until != null);

    return GuardianSnapshot(
      patient: PatientStatus.fromJson(json['patient'] as Map<String, dynamic>),
      alerts: List.unmodifiable(
        alerts.map(
          (alert) => GuardianAlert.fromJson(alert as Map<String, dynamic>),
        ),
      ),
      activity: ActivitySummary.fromJson(
        json['activity'] as Map<String, dynamic>,
      ),
      doorEvents: List.unmodifiable(
        doorEvents.map(
          (event) => DoorEvent.fromJson(event as Map<String, dynamic>),
        ),
      ),
      demoScenario: DemoScenario.fromJson(
        json['demo_scenario'] as String? ?? 'repetitive_behavior',
      ),
      repetitiveAlertPauseUntil: available && pause?['is_paused'] == true
          ? until
          : null,
      repetitiveAlertPauseAvailable: available,
    );
  }

  GuardianAlert get repetitiveBehaviorAlert =>
      alerts.firstWhere((alert) => alert.isRepetitiveBehavior);
}
