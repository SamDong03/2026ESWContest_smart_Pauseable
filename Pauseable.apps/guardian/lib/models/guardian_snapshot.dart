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
  });

  final PatientStatus patient;
  final List<GuardianAlert> alerts;
  final ActivitySummary activity;
  final List<DoorEvent> doorEvents;
  final DemoScenario demoScenario;

  factory GuardianSnapshot.fromJson(Map<String, dynamic> json) {
    final alerts = json['alerts'] as List<dynamic>;
    final doorEvents = json['door_events'] as List<dynamic>? ?? const [];

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
    );
  }

  GuardianAlert get repetitiveBehaviorAlert =>
      alerts.firstWhere((alert) => alert.isRepetitiveBehavior);
}
