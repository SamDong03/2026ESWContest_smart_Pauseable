class VoiceTrainingProgress {
  const VoiceTrainingProgress({
    required this.targetSeconds,
    required this.recordedSeconds,
    required this.clipCount,
    required this.isReady,
    this.jobId,
    this.jobStatus = 'collecting',
    this.totalPrompts = 160,
  });

  const VoiceTrainingProgress.empty()
    : targetSeconds = 800,
      recordedSeconds = 0,
      clipCount = 0,
      isReady = false,
      jobId = null,
      jobStatus = 'not_started',
      totalPrompts = 160;

  final String? jobId;
  final String jobStatus;
  final int totalPrompts;

  factory VoiceTrainingProgress.fromJson(Map<String, dynamic> json) {
    return VoiceTrainingProgress(
      targetSeconds: json['target_seconds'] as int,
      recordedSeconds: json['recorded_seconds'] as int,
      clipCount: json['clip_count'] as int,
      isReady: json['is_ready'] as bool,
      jobId: json['job_id'] as String?,
      jobStatus: json['job_status'] as String? ?? 'collecting',
      totalPrompts: json['total_prompts'] as int? ?? 160,
    );
  }

  final int targetSeconds;
  final int recordedSeconds;
  final int clipCount;
  final bool isReady;

  bool get canRecord =>
      (jobStatus == 'not_started' || jobStatus == 'collecting') &&
      clipCount < totalPrompts;
  bool get canStartNewTraining => jobStatus == 'completed' && jobId != null;
  String get statusLabel => switch (jobStatus) {
    'not_started' || 'collecting' => '녹음 수집 중',
    'queued' => '학습 대기 중',
    'claimed' || 'downloading' => '학습 준비 중',
    'preprocessing' => '녹음 전처리 중',
    'training' => '음성 학습 중',
    'exporting' || 'validating_model' => '음성 모델 검증 중',
    'uploading' => '학습 모델 저장 중',
    'completed' => '음성 학습 완료',
    'failed' => '학습 실패 · 담당자 확인 필요',
    _ => '학습 상태 확인 필요',
  };

  int get remainingSeconds =>
      (targetSeconds - recordedSeconds).clamp(0, targetSeconds);

  double get fraction {
    if (targetSeconds == 0) return 0;
    return (recordedSeconds / targetSeconds).clamp(0, 1);
  }
}
