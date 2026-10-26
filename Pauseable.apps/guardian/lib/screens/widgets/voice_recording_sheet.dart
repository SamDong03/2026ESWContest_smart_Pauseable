part of '../guardian_home_page.dart';

enum _VoiceRecordingStep {
  loading,
  idle,
  recording,
  processing,
  ready,
  uploading,
}

class _VoiceRecordingSheet extends StatefulWidget {
  const _VoiceRecordingSheet({
    required this.repository,
    required this.recorderFactory,
    required this.hasVoiceConsent,
  });

  final GuardianRepository repository;
  final VoiceRecorderFactory recorderFactory;
  final bool hasVoiceConsent;

  @override
  State<_VoiceRecordingSheet> createState() => _VoiceRecordingSheetState();
}

class _VoiceRecordingSheetState extends State<_VoiceRecordingSheet> {
  static const _maxClipSeconds = 45;

  VoiceRecordingService? _recorder;
  _VoiceRecordingStep _step = _VoiceRecordingStep.loading;
  VoiceTrainingProgress _progress = const VoiceTrainingProgress.empty();
  VoiceTrainingScript? _script;
  VoiceRecording? _recording;
  Timer? _timer;
  int _elapsedSeconds = 0;
  VoiceTrainingPrompt? _recordingPrompt;
  String? _errorMessage;
  String? _successMessage;
  String? _recordingJobId;
  bool _progressLoaded = false;
  bool _startingSession = false;

  VoiceTrainingPrompt? get _currentPrompt {
    final script = _script;
    return script?.promptForClipCount(_progress.clipCount);
  }

  @override
  void initState() {
    super.initState();
    if (widget.hasVoiceConsent) {
      unawaited(_loadProgress());
    } else {
      _step = _VoiceRecordingStep.idle;
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    final recorder = _recorder;
    if (recorder != null) unawaited(recorder.dispose());
    super.dispose();
  }

  Future<void> _loadProgress() async {
    if (!widget.hasVoiceConsent) return;
    setState(() {
      _step = _VoiceRecordingStep.loading;
      _progressLoaded = false;
      _errorMessage = null;
    });
    try {
      final script = await VoiceTrainingScriptLoader.load();
      final progress = await widget.repository.loadVoiceTrainingProgress();
      if (!mounted) return;
      setState(() {
        _script = script;
        _progress = progress;
        _progressLoaded = true;
        _step = _VoiceRecordingStep.idle;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _step = _VoiceRecordingStep.idle;
        _errorMessage = '학습 진행 상황을 불러오지 못했습니다. 서버 연결을 확인해 주세요.';
      });
    }
  }

  Future<void> _startRecording() async {
    if (!widget.hasVoiceConsent ||
        !_progressLoaded ||
        !_progress.canRecord ||
        _startingSession) {
      return;
    }
    if (_step != _VoiceRecordingStep.idle &&
        _step != _VoiceRecordingStep.ready) {
      return;
    }
    final prompt = _currentPrompt;
    if (prompt == null) {
      setState(() {
        _errorMessage =
            _script != null && _progress.clipCount >= _script!.totalPrompts
            ? '${_script!.totalPrompts}개 문장 녹음이 완료되었습니다.'
            : '녹음 대본을 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.';
      });
      return;
    }
    setState(() {
      _errorMessage = null;
      _successMessage = null;
      _recording = null;
      _recordingPrompt = prompt;
      _recordingJobId = _progress.jobId;
      _step = _VoiceRecordingStep.processing;
    });

    try {
      final recorder = _recorder ??= widget.recorderFactory();
      final allowed = await recorder.start();
      if (!mounted) return;
      if (!allowed) {
        setState(() {
          _step = _VoiceRecordingStep.idle;
          _errorMessage = '마이크 권한이 필요합니다. 휴대폰 설정에서 마이크 권한을 허용해 주세요.';
        });
        return;
      }

      setState(() {
        _step = _VoiceRecordingStep.recording;
        _elapsedSeconds = 0;
      });
      _timer = Timer.periodic(const Duration(seconds: 1), (timer) {
        if (!mounted) return;
        setState(() => _elapsedSeconds++);
        if (_elapsedSeconds >= _maxClipSeconds) {
          timer.cancel();
          unawaited(_stopRecording());
        }
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _step = _VoiceRecordingStep.idle;
        _errorMessage = '녹음을 시작하지 못했습니다. 마이크 연결과 권한을 확인해 주세요.';
      });
    }
  }

  Future<void> _stopRecording() async {
    final recorder = _recorder;
    if (!widget.hasVoiceConsent ||
        recorder == null ||
        _step != _VoiceRecordingStep.recording) {
      return;
    }
    _timer?.cancel();
    setState(() => _step = _VoiceRecordingStep.processing);

    try {
      final recording = await recorder.stop();
      if (!mounted) return;
      setState(() {
        _recording = recording;
        _step = _VoiceRecordingStep.ready;
      });
      await _uploadRecording();
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _step = _VoiceRecordingStep.idle;
        _errorMessage = '음성 파일을 만들지 못했습니다. 1초 이상 읽은 뒤 다시 시도해 주세요.';
      });
    }
  }

  Future<void> _uploadRecording() async {
    if (!widget.hasVoiceConsent) return;
    final recording = _recording;
    final prompt = _recordingPrompt;
    if (recording == null ||
        prompt == null ||
        _step == _VoiceRecordingStep.uploading) {
      return;
    }
    final hadReachedRecommendation = _progress.isReady;
    setState(() {
      _step = _VoiceRecordingStep.uploading;
      _errorMessage = null;
    });

    try {
      final progress = await widget.repository.uploadVoiceTrainingClip(
        audioBytes: recording.bytes,
        fileName: prompt.fileName,
        durationSeconds: _displayDuration(recording),
        promptText: prompt.text,
        jobId: _recordingJobId,
      );
      if (!mounted) return;
      setState(() {
        _progress = progress;
        _recording = null;
        _recordingPrompt = null;
        _recordingJobId = null;
        _step = _VoiceRecordingStep.idle;
        _successMessage = !progress.canRecord
            ? '${prompt.fileName} 저장 완료 · ${progress.statusLabel}'
            : progress.isReady
            ? hadReachedRecommendation
                  ? '${prompt.fileName} 저장 완료 · 누적 ${progress.recordedSeconds}초예요. 추가 녹음이 TTS 품질 향상에 반영됩니다.'
                  : '권장 800초를 달성했습니다. 계속 녹음하면 TTS 품질을 더 높일 수 있어요.'
            : '${prompt.fileName} 저장 완료 · 누적 ${progress.recordedSeconds}초예요.';
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _step = _VoiceRecordingStep.ready;
        _errorMessage =
            '자동 전송에 실패했습니다. 녹음은 이 화면에 남아 있어요. 연결을 확인한 뒤 다시 전송해 주세요.';
      });
    }
  }

  int _displayDuration(VoiceRecording recording) =>
      (recording.duration.inMilliseconds / 1000).ceil().clamp(
        1,
        _maxClipSeconds,
      );

  Future<void> _startNewTraining() async {
    if (!widget.hasVoiceConsent ||
        _startingSession ||
        !_progress.canStartNewTraining) {
      return;
    }
    final previousJobId = _progress.jobId!;
    final confirmed = await showDialog<bool>(
      context: context,
      builder: (dialogContext) => AlertDialog(
        title: const Text('새 음성학습을 시작할까요?'),
        content: const Text(
          '현재 사용하는 목소리는 유지하고 새 세트의 1번 문장부터 녹음합니다. 새 모델이 장비에서 검증·설치되기 전까지 기존 목소리를 사용합니다. 원본 녹음은 설치·검증 성공 확인 후 24시간 또는 학습 세트 생성 후 14일 중 먼저 도래한 기한부터 삭제 대상이며, 교체된 이전 모델은 7일 후 삭제 대상입니다.',
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(dialogContext, false),
            child: const Text('취소'),
          ),
          FilledButton(
            onPressed: () => Navigator.pop(dialogContext, true),
            child: const Text('새 학습 시작'),
          ),
        ],
      ),
    );
    if (confirmed != true || !mounted) return;
    setState(() {
      _startingSession = true;
      _errorMessage = null;
      _successMessage = null;
    });
    try {
      final progress = await widget.repository.startNewVoiceTraining(
        previousJobId: previousJobId,
      );
      if (!mounted) return;
      setState(() {
        _progress = progress;
        _recording = null;
        _recordingPrompt = null;
        _recordingJobId = null;
        _elapsedSeconds = 0;
        _step = _VoiceRecordingStep.idle;
        _successMessage = progress.canRecord
            ? '새 학습 세트를 확인했어요. 기존 목소리는 유지되며 ${progress.clipCount + 1}번 문장부터 녹음할 수 있어요.'
            : '${progress.statusLabel} · 기존 목소리는 유지됩니다.';
      });
    } catch (_) {
      if (mounted) {
        setState(
          () => _errorMessage = '새 학습 세트를 시작하지 못했습니다. 현재 사용하는 목소리는 유지됩니다. 연결과 학습 상태를 확인한 뒤 다시 시도해 주세요.',
        );
      }
    } finally {
      if (mounted) setState(() => _startingSession = false);
    }
  }

  Future<void> _close() async {
    if (_step == _VoiceRecordingStep.ready) {
      final discard = await showDialog<bool>(
        context: context,
        builder: (dialogContext) => AlertDialog(
          title: const Text('전송하지 못한 녹음이 있어요'),
          content: const Text('이 화면을 닫으면 아직 전송되지 않은 이 문장 녹음이 사라집니다.'),
          actions: [
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, false),
              child: const Text('계속 전송하기'),
            ),
            TextButton(
              onPressed: () => Navigator.pop(dialogContext, true),
              child: const Text('녹음 버리고 닫기'),
            ),
          ],
        ),
      );
      if (discard != true || !mounted) return;
    }
    if (mounted) Navigator.pop(context);
  }

  String _formatDuration(int seconds) {
    final minutes = seconds ~/ 60;
    final remainder = seconds % 60;
    if (minutes == 0) return '$remainder초';
    return remainder == 0 ? '$minutes분' : '$minutes분 $remainder초';
  }

  @override
  Widget build(BuildContext context) {
    if (!widget.hasVoiceConsent) {
      return SafeArea(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            const Text('음성 수집·이용에 동의한 후 녹음할 수 있습니다.'),
            TextButton(onPressed: _close, child: const Text('돌아가기')),
          ],
        ),
      );
    }
    final isBusy =
        _step == _VoiceRecordingStep.loading ||
        _step == _VoiceRecordingStep.processing ||
        _step == _VoiceRecordingStep.uploading ||
        _startingSession;
    return PopScope(
      canPop: _step == _VoiceRecordingStep.idle && !_startingSession,
      onPopInvokedWithResult: (didPop, result) {
        if (!didPop && _step == _VoiceRecordingStep.ready) unawaited(_close());
      },
      child: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.fromLTRB(20, 0, 20, 24),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Align(
                alignment: Alignment.centerRight,
                child: TextButton.icon(
                  onPressed: isBusy || _step == _VoiceRecordingStep.recording
                      ? null
                      : _close,
                  icon: const Icon(Icons.close),
                  label: const Text('녹음 화면 닫기'),
                ),
              ),
              Text(
                '보호자 목소리 학습',
                style: TextStyle(
                  color: _primaryText(context),
                  fontSize: 22,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 7),
              Text(
                '각 문장의 녹음을 완료하면 자동으로 서버에 전송합니다. 권장 녹음 분량은 800초이며 현재 ${_script?.totalPrompts ?? 160}개 문장을 녹음할 수 있어요.',
                style: TextStyle(color: _secondaryText(context), height: 1.45),
              ),
              const SizedBox(height: 16),
              if (_progress.canRecord) _buildQuietRecordingNotice(),
              const SizedBox(height: 12),
              _buildProgressCard(),
              const SizedBox(height: 12),
              if (_progress.canRecord || _recording != null) ...[
                _buildPromptCard(),
                const SizedBox(height: 12),
                _buildRecordingCard(isBusy),
              ] else ...[
                _buildMessage(
                  '${_progress.statusLabel}\n새 모델이 장비에서 검증·설치되기 전까지 현재 목소리를 사용합니다. 원본 녹음과 교체된 모델은 안내한 보관·삭제 정책에 따라 처리됩니다.',
                  true,
                ),
              ],
              if (_successMessage != null) ...[
                const SizedBox(height: 10),
                _buildMessage(_successMessage!, true),
              ],
              if (_errorMessage != null) ...[
                const SizedBox(height: 10),
                _buildMessage(_errorMessage!, false),
              ],
              const SizedBox(height: 16),
              _buildActionButtons(isBusy),
              const SizedBox(height: 9),
              Text(
                '같은 장소에서 휴대폰을 입에서 15~20cm 떨어뜨리고, 문장 앞뒤로 잠깐 무음을 둔 채 평소의 따뜻한 목소리로 읽어 주세요.',
                style: TextStyle(color: _secondaryText(context), fontSize: 11),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildQuietRecordingNotice() {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _softSurface(context),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          const Icon(Icons.volume_off_rounded, color: _green),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  '조용한 곳에서 녹음해 주세요',
                  style: TextStyle(
                    color: _primaryText(context),
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 4),
                Text(
                  'TV·음악을 끄고 주변 대화와 바람 소리를 줄여 주세요. 같은 거리에서 평소 목소리로 또박또박 읽어 주세요.',
                  style: TextStyle(
                    color: _secondaryText(context),
                    fontSize: 12,
                    height: 1.45,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildProgressCard() {
    final additionalSeconds =
        (_progress.recordedSeconds - _progress.targetSeconds).clamp(
          0,
          _progress.recordedSeconds,
        );
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(15),
      decoration: BoxDecoration(
        color: _softSurface(context),
        borderRadius: BorderRadius.circular(18),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              const Icon(Icons.graphic_eq_rounded, color: _green),
              const SizedBox(width: 8),
              Text(
                '음성 학습 진행',
                style: TextStyle(
                  color: _primaryText(context),
                  fontWeight: FontWeight.w900,
                ),
              ),
              const Spacer(),
              Text(
                _progress.isReady
                    ? '${_progress.recordedSeconds}초 · 권장 ${_progress.targetSeconds}초'
                    : '${_progress.recordedSeconds} / ${_progress.targetSeconds}초 권장',
                style: const TextStyle(
                  color: _green,
                  fontWeight: FontWeight.w900,
                ),
              ),
            ],
          ),
          const SizedBox(height: 11),
          LinearProgressIndicator(
            value: _progress.fraction,
            minHeight: 9,
            borderRadius: BorderRadius.circular(20),
            backgroundColor: _surfaceColor(context),
          ),
          const SizedBox(height: 8),
          Text(
            _progress.isReady
                ? additionalSeconds > 0
                      ? '권장 분량 달성 · 추가 ${_formatDuration(additionalSeconds)} 녹음 · 클립 ${_progress.clipCount}개'
                      : '권장 분량 달성 · 계속 녹음하면 TTS 품질이 더 높아져요'
                : '클립 ${_progress.clipCount}개 · 권장 분량까지 ${_formatDuration(_progress.remainingSeconds)} 남음',
            style: TextStyle(color: _secondaryText(context), fontSize: 12),
          ),
        ],
      ),
    );
  }

  Widget _buildPromptCard() {
    final prompt = _recordingPrompt ?? _currentPrompt;
    final totalPrompts = _script?.totalPrompts ?? 160;
    final isAdditionalRecording = _progress.clipCount >= totalPrompts;
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(15),
      decoration: BoxDecoration(
        color: const Color(0xFFFFFAF1),
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: const Color(0xFFF0DFC3)),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Text(
                prompt == null
                    ? '녹음 대본 확인'
                    : isAdditionalRecording
                    ? '추가 녹음 ${_progress.clipCount - totalPrompts + 1} · 대본 ${prompt.index} / $totalPrompts'
                    : '문장 ${prompt.index} / $totalPrompts',
                style: const TextStyle(
                  color: Color(0xFF9A672F),
                  fontSize: 12,
                  fontWeight: FontWeight.w800,
                ),
              ),
              const Spacer(),
              if (prompt != null)
                Text(
                  prompt.fileName,
                  style: const TextStyle(
                    color: Color(0xFF9A672F),
                    fontSize: 12,
                    fontWeight: FontWeight.w900,
                  ),
                ),
            ],
          ),
          const SizedBox(height: 8),
          Text(
            prompt?.text ??
                (_script != null && _progress.clipCount >= totalPrompts
                    ? '$totalPrompts개 문장 녹음이 완료되었습니다.'
                    : '녹음 대본을 불러오지 못했습니다.'),
            style: const TextStyle(
              color: _dark,
              fontSize: 15,
              height: 1.5,
              fontWeight: FontWeight.w700,
            ),
          ),
          if (prompt != null) ...[
            const SizedBox(height: 12),
            Wrap(
              spacing: 6,
              runSpacing: 6,
              children: [
                _buildPromptTag(prompt.category),
                _buildPromptTag(prompt.tone),
                if (prompt.addressee != null)
                  _buildPromptTag('호칭 · ${prompt.addressee}'),
              ],
            ),
          ],
        ],
      ),
    );
  }

  Widget _buildPromptTag(String label) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
      decoration: BoxDecoration(
        color: const Color(0xFFFFF3DD),
        borderRadius: BorderRadius.circular(20),
      ),
      child: Text(
        label,
        style: const TextStyle(
          color: Color(0xFF8A602B),
          fontSize: 11,
          fontWeight: FontWeight.w700,
        ),
      ),
    );
  }

  Widget _buildRecordingCard(bool isBusy) {
    final recording = _recording;
    final label = switch (_step) {
      _VoiceRecordingStep.loading => '진행 상황 불러오는 중',
      _VoiceRecordingStep.recording => '문장을 읽어 주세요',
      _VoiceRecordingStep.processing => '음성 파일 만드는 중',
      _VoiceRecordingStep.ready => '전송 대기 · 녹음 보관 중',
      _VoiceRecordingStep.uploading => '이 문장을 서버에 전송하는 중',
      _ => '한 문장당 WAV 파일 하나로 저장해요',
    };
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(14),
      decoration: BoxDecoration(
        color: _step == _VoiceRecordingStep.recording
            ? const Color(0xFFFFEEEE)
            : _softSurface(context),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Icon(
            Icons.mic_rounded,
            color: isBusy ? _secondaryText(context) : _green,
          ),
          const SizedBox(width: 10),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                if (_step == _VoiceRecordingStep.recording)
                  Text(
                    '00:${_elapsedSeconds.toString().padLeft(2, '0')} / 00:45',
                    style: const TextStyle(color: Color(0xFFB53E3E)),
                  )
                else if (recording != null)
                  Text(
                    '${_displayDuration(recording)}초 · ${(recording.bytes.length / 1024).toStringAsFixed(1)} KB · WAV',
                    style: TextStyle(
                      color: _secondaryText(context),
                      fontSize: 12,
                    ),
                  ),
              ],
            ),
          ),
          if (isBusy)
            const SizedBox(
              width: 20,
              height: 20,
              child: CircularProgressIndicator(strokeWidth: 2.2),
            ),
        ],
      ),
    );
  }

  Widget _buildMessage(String message, bool success) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(11),
      decoration: BoxDecoration(
        color: success ? const Color(0xFFE6F3EE) : const Color(0xFFFFEEEE),
        borderRadius: BorderRadius.circular(12),
      ),
      child: Text(
        message,
        style: TextStyle(
          color: success ? _green : const Color(0xFF9C3434),
          height: 1.35,
        ),
      ),
    );
  }

  Widget _buildActionButtons(bool isBusy) {
    final totalPrompts = _script?.totalPrompts ?? 160;
    if (!_progressLoaded || (!_progress.canRecord && _recording == null)) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          if (_progressLoaded && _progress.canStartNewTraining)
            FilledButton.icon(
              onPressed: isBusy ? null : _startNewTraining,
              icon: const Icon(Icons.add_circle_outline),
              label: Text(_startingSession ? '새 학습 세트 준비 중…' : '새 음성학습 시작'),
            ),
          OutlinedButton.icon(
            onPressed: isBusy ? null : _loadProgress,
            icon: const Icon(Icons.refresh),
            label: const Text('학습 상태 새로고침'),
          ),
        ],
      );
    }
    if (_step == _VoiceRecordingStep.recording) {
      return SizedBox(
        width: double.infinity,
        child: FilledButton.icon(
          onPressed: _stopRecording,
          style: FilledButton.styleFrom(
            backgroundColor: const Color(0xFFB53E3E),
          ),
          icon: const Icon(Icons.stop_rounded),
          label: const Text('이 문장 녹음 완료 · 자동 전송'),
        ),
      );
    }
    if (_step == _VoiceRecordingStep.ready) {
      return Column(
        children: [
          SizedBox(
            width: double.infinity,
            child: FilledButton.icon(
              onPressed: _uploadRecording,
              icon: const Icon(Icons.library_add_check_outlined),
              label: const Text('이 문장 다시 전송'),
            ),
          ),
          const SizedBox(height: 7),
          SizedBox(
            width: double.infinity,
            child: OutlinedButton.icon(
              onPressed: _startRecording,
              icon: const Icon(Icons.refresh_rounded),
              label: const Text('이 문장 다시 녹음'),
            ),
          ),
        ],
      );
    }
    return SizedBox(
      width: double.infinity,
      child: FilledButton.icon(
        onPressed:
            isBusy ||
                (_script != null &&
                    _progress.clipCount >= _script!.totalPrompts)
            ? null
            : _currentPrompt == null
            ? _loadProgress
            : _startRecording,
        icon: const Icon(Icons.mic_none_rounded),
        label: Text(
          _script != null && _progress.clipCount >= _script!.totalPrompts
              ? '$totalPrompts개 문장 녹음 완료'
              : _currentPrompt == null
              ? '녹음 대본 다시 불러오기'
              : _progress.isReady
              ? '추가 녹음 시작'
              : '이 문장 녹음 시작',
        ),
      ),
    );
  }
}
