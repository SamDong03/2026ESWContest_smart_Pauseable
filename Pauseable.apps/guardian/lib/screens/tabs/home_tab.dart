part of '../guardian_home_page.dart';

extension _GuardianHomeView on _GuardianHomePageState {
  Widget _buildHomeTab(BuildContext context, GuardianSnapshot snapshot) {
    return SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 620),
          child: CustomScrollView(
            slivers: [
              SliverPadding(
                padding: const EdgeInsets.fromLTRB(20, 18, 20, 28),
                sliver: SliverList.list(
                  children: [
                    _buildHeader(context),
                    if (widget.liveAlertClient != null) ...[
                      const SizedBox(height: 12),
                      _buildLiveAlertConnectionBanner(context),
                    ],
                    const SizedBox(height: 24),
                    Text(
                      '안녕하세요, ${_guardianProfile?.guardianLabel ?? '보호자님'}',
                      style: TextStyle(
                        color: _secondaryText(context),
                        fontSize: 15,
                        fontWeight: FontWeight.w500,
                      ),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '오늘도 편안하게 지켜볼게요',
                      style: TextStyle(
                        color: _primaryText(context),
                        fontSize: 26,
                        height: 1.25,
                        fontWeight: FontWeight.w800,
                        letterSpacing: -0.8,
                      ),
                    ),
                    const SizedBox(height: 18),
                    if (!_loadingProfile &&
                        (_profileLoadFailed ||
                            _guardianProfile?.hasNames != true)) ...[
                      _buildProfileSetupCard(context),
                      const SizedBox(height: 18),
                    ],
                    _buildVoiceTrainingHomeCard(context),
                    const SizedBox(height: 22),
                    _buildPatientIdentityCard(),
                    if (snapshot.doorEvents.isNotEmpty) ...[
                      const SizedBox(height: 26),
                      _sectionHeader(
                        title: '최근 출입 장면',
                        action: '기록보기',
                        onPressed: () => _selectTab(2),
                      ),
                      const SizedBox(height: 12),
                      _buildDoorEventCard(
                        snapshot.doorEvents.first,
                        confirmed: _isDoorEventConfirmed(
                          snapshot.doorEvents.first,
                        ),
                      ),
                    ],
                    if (snapshot.demoScenario ==
                            DemoScenario.repetitiveBehavior ||
                        snapshot.repetitiveAlertsPaused ||
                        snapshot.alerts.any(
                          (alert) =>
                              alert.isRepetitiveBehavior && alert.isServerAlert,
                        )) ...[
                      const SizedBox(height: 26),
                      _buildBehaviorAlertCard(
                        context,
                        snapshot.repetitiveBehaviorAlert,
                      ),
                    ],
                    const SizedBox(height: 26),
                    _sectionHeader(
                      title: '최근 알림',
                      action: '전체보기',
                      onPressed: () => _selectTab(1),
                    ),
                    const SizedBox(height: 12),
                    _buildAlertCard(snapshot.alerts),
                    const SizedBox(height: 26),
                    Text(
                      '빠른 실행',
                      style: TextStyle(
                        color: _primaryText(context),
                        fontSize: 19,
                        fontWeight: FontWeight.w800,
                      ),
                    ),
                    const SizedBox(height: 12),
                    _buildQuickActions(context),
                    const SizedBox(height: 14),
                    _buildEmergencyButton(context),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildProfileSetupCard(BuildContext context) {
    return Card(
      child: ListTile(
        leading: Icon(
          _profileLoadFailed
              ? Icons.sync_problem_rounded
              : Icons.person_add_alt_1_outlined,
        ),
        title: Text(
          _profileLoadFailed ? '돌봄 정보를 불러오지 못했어요' : '보호자와 대상자 이름을 등록해 주세요',
        ),
        subtitle: Text(
          _profileLoadFailed
              ? '서버 연결을 확인한 뒤 다시 시도해 주세요.'
              : '이름을 등록하면 나에게 맞는 홈 화면을 볼 수 있어요.',
        ),
        trailing: TextButton(
          onPressed: _profileLoadFailed
              ? _loadGuardianProfile
              : _editGuardianProfile,
          child: Text(_profileLoadFailed ? '재시도' : '정보 등록'),
        ),
      ),
    );
  }

  Widget _buildLiveAlertConnectionBanner(BuildContext context) {
    final (label, color, icon) = switch (_liveAlertStatus) {
      LiveAlertConnectionStatus.connected => (
        '실시간 알림 서버 연결됨',
        const Color(0xFF2F7D5C),
        Icons.wifi_rounded,
      ),
      LiveAlertConnectionStatus.connecting => (
        '실시간 알림 서버 연결 중',
        const Color(0xFF4C6B9C),
        Icons.sync_rounded,
      ),
      LiveAlertConnectionStatus.reconnecting => (
        '연결이 끊겨 다시 연결 중',
        const Color(0xFFB56A24),
        Icons.sync_problem_rounded,
      ),
      LiveAlertConnectionStatus.stopped => (
        '실시간 알림 연결 중지됨',
        const Color(0xFFC24B4B),
        Icons.wifi_off_rounded,
      ),
    };

    return AnimatedContainer(
      duration: const Duration(milliseconds: 250),
      padding: const EdgeInsets.symmetric(horizontal: 13, vertical: 9),
      decoration: BoxDecoration(
        color: color.withValues(alpha: 0.10),
        borderRadius: BorderRadius.circular(13),
        border: Border.all(color: color.withValues(alpha: 0.24)),
      ),
      child: Row(
        children: [
          Icon(icon, color: color, size: 18),
          const SizedBox(width: 8),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  label,
                  style: TextStyle(
                    color: color,
                    fontSize: 12,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 3),
                Text(
                  '앱과 알림 서버의 연결 상태이며, 환자·센서의 상태와는 별개예요.',
                  style: TextStyle(
                    color: _secondaryText(context),
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildHeader(BuildContext context) {
    return Row(
      children: [
        Container(
          width: 42,
          height: 42,
          decoration: BoxDecoration(
            color: _green,
            borderRadius: BorderRadius.circular(13),
          ),
          alignment: Alignment.center,
          child: const Text(
            'P',
            style: TextStyle(
              color: Colors.white,
              fontSize: 22,
              fontWeight: FontWeight.w900,
            ),
          ),
        ),
        const SizedBox(width: 11),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                'PAUSEABLE',
                style: TextStyle(
                  color: _primaryText(context),
                  fontSize: 17,
                  fontWeight: FontWeight.w900,
                  letterSpacing: 0.5,
                ),
              ),
              Text(
                '보호자 케어',
                style: TextStyle(color: _secondaryText(context), fontSize: 12),
              ),
            ],
          ),
        ),
        IconButton.filledTonal(
          onPressed: () => _selectTab(1),
          tooltip: '알림',
          icon: const Icon(Icons.notifications_none_rounded),
        ),
      ],
    );
  }

  Widget _buildPatientIdentityCard() {
    return Container(
      key: const ValueKey('care-patient-identity'),
      padding: const EdgeInsets.all(20),
      decoration: BoxDecoration(
        gradient: const LinearGradient(
          colors: [Color(0xFF356B5A), Color(0xFF4A8874)],
          begin: Alignment.topLeft,
          end: Alignment.bottomRight,
        ),
        borderRadius: BorderRadius.circular(24),
        boxShadow: const [
          BoxShadow(
            color: Color(0x26356B5A),
            blurRadius: 24,
            offset: Offset(0, 12),
          ),
        ],
      ),
      child: Row(
        children: [
          Container(
            width: 48,
            height: 48,
            decoration: BoxDecoration(
              color: Colors.white.withValues(alpha: 0.16),
              shape: BoxShape.circle,
            ),
            child: const Icon(
              Icons.person_rounded,
              color: Colors.white,
              size: 30,
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Text(
                  '돌봄 대상자',
                  style: TextStyle(color: Color(0xFFDCEBE5), fontSize: 11),
                ),
                const SizedBox(height: 4),
                Text(
                  _guardianProfile?.patientLabel ?? '이름을 등록해 주세요',
                  style: const TextStyle(
                    color: Colors.white,
                    fontSize: 21,
                    fontWeight: FontWeight.w800,
                  ),
                ),
                const SizedBox(height: 5),
                const Text(
                  '알림과 출입 기록에서 상황을 확인하세요.',
                  style: TextStyle(color: Color(0xFFDCEBE5), fontSize: 12),
                ),
              ],
            ),
          ),
          IconButton(
            onPressed: _refreshSnapshot,
            tooltip: '알림·출입 기록 새로고침',
            icon: const Icon(Icons.refresh_rounded, color: Colors.white),
          ),
        ],
      ),
    );
  }

  Widget _sectionHeader({
    required String title,
    required String action,
    required VoidCallback onPressed,
  }) {
    return Row(
      children: [
        Expanded(
          child: Text(
            title,
            style: TextStyle(
              color: _primaryText(context),
              fontSize: 19,
              fontWeight: FontWeight.w800,
            ),
          ),
        ),
        TextButton(onPressed: onPressed, child: Text(action)),
      ],
    );
  }

  Widget _buildDoorEventCard(DoorEvent event, {required bool confirmed}) {
    return Semantics(
      button: true,
      label: '최근 출입 장면 상세보기',
      child: Card(
        clipBehavior: Clip.antiAlias,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(22)),
        child: InkWell(
          onTap: () => _showDoorEventDetail(event),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              AspectRatio(
                aspectRatio: 16 / 9,
                child: Stack(
                  fit: StackFit.expand,
                  children: [
                    _DoorEventImage(
                      imageUrl: event.imageUrl,
                      loadBytes: () => _loadDoorPhoto(event),
                      semanticLabel: '${event.directionLabel} 당시 현관 장면',
                    ),
                    Positioned(
                      top: 12,
                      left: 12,
                      child: Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 10,
                          vertical: 6,
                        ),
                        decoration: BoxDecoration(
                          color: const Color(0xD918332B),
                          borderRadius: BorderRadius.circular(20),
                        ),
                        child: Row(
                          mainAxisSize: MainAxisSize.min,
                          children: [
                            const Icon(
                              Icons.directions_walk_rounded,
                              color: Colors.white,
                              size: 16,
                            ),
                            const SizedBox(width: 5),
                            Text(
                              event.directionLabel,
                              style: const TextStyle(
                                color: Colors.white,
                                fontSize: 12,
                                fontWeight: FontWeight.w800,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            event.title,
                            style: TextStyle(
                              color: _primaryText(context),
                              fontSize: 17,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                        ),
                        Text(
                          confirmed ? '확인 완료' : event.timeLabel,
                          style: TextStyle(
                            color: confirmed ? _green : _secondaryText(context),
                            fontSize: 11,
                            fontWeight: confirmed
                                ? FontWeight.w800
                                : FontWeight.w500,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    Row(
                      children: [
                        const Icon(
                          Icons.camera_alt_outlined,
                          size: 17,
                          color: _green,
                        ),
                        const SizedBox(width: 6),
                        Expanded(
                          child: Text(
                            '현관 카메라 샘플 촬영',
                            style: TextStyle(
                              color: _secondaryText(context),
                              fontSize: 12,
                            ),
                          ),
                        ),
                        const Text(
                          '장면 확인하기',
                          style: TextStyle(
                            color: _green,
                            fontSize: 12,
                            fontWeight: FontWeight.w800,
                          ),
                        ),
                        const SizedBox(width: 3),
                        const Icon(
                          Icons.chevron_right_rounded,
                          color: _green,
                          size: 18,
                        ),
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildBehaviorAlertCard(BuildContext context, GuardianAlert alert) {
    final isPaused = _pausedAnomalyDuration != null;
    final hasCount = alert.currentCount != null;
    final hasNormalRange =
        hasCount && alert.normalMin != null && alert.normalMax != null;
    final accent = isPaused ? _green : const Color(0xFFB56A24);
    final accentBackground = isPaused
        ? const Color(0xFFE5F1EC)
        : const Color(0xFFFFF4E8);

    return Card(
      key: const ValueKey('home-behavior-alert'),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(22),
        side: BorderSide(color: accent.withValues(alpha: 0.24)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(18),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Container(
                  width: 44,
                  height: 44,
                  decoration: BoxDecoration(
                    color: accentBackground,
                    borderRadius: BorderRadius.circular(13),
                  ),
                  child: Icon(
                    isPaused
                        ? Icons.notifications_paused_outlined
                        : Icons.repeat_rounded,
                    color: accent,
                  ),
                ),
                const SizedBox(width: 13),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        isPaused
                            ? '반복 행동 알림 일시 중지됨'
                            : hasCount
                            ? '반복 행동 확인 필요'
                            : '반복행동 감지',
                        style: TextStyle(
                          color: _primaryText(context),
                          fontSize: 17,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      const SizedBox(height: 4),
                      Text(
                        '감지 시각 · ${alert.timeLabel}',
                        style: TextStyle(
                          color: _secondaryText(context),
                          fontSize: 12,
                        ),
                      ),
                      const SizedBox(height: 6),
                      Text(
                        isPaused
                            ? '반복행동 알림을 $_pausedAnomalyDuration 보내지 않아요.'
                            : alert.description,
                        style: TextStyle(
                          color: _secondaryText(context),
                          fontSize: 13,
                          height: 1.4,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 15),
            if (isPaused) ...[
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(12),
                decoration: BoxDecoration(
                  color: _softSurface(context),
                  borderRadius: BorderRadius.circular(12),
                ),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.shield_outlined, color: _green, size: 18),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        '배회 알림·출입 사진 수신과 감지 기록은 유지됩니다. 감지·TTS·가전 동작은 중단하지 않습니다.',
                        style: TextStyle(
                          color: _secondaryText(context),
                          fontSize: 12,
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 12),
              SizedBox(
                width: double.infinity,
                child: OutlinedButton.icon(
                  onPressed: _updatingAnomalyPause
                      ? null
                      : _resumeAnomalyAlerts,
                  icon: const Icon(Icons.notifications_active_outlined),
                  label: const Text('알림 다시 켜기'),
                ),
              ),
            ] else ...[
              if (!(_snapshot?.repetitiveAlertPauseAvailable ?? false))
                const Padding(
                  padding: EdgeInsets.only(bottom: 12),
                  child: Text('알림 중지 상태를 확인하지 못했습니다. 서버 연결 후 새로고침해 주세요.'),
                ),
              if (hasCount) ...[
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 12,
                  ),
                  decoration: BoxDecoration(
                    color: const Color(0xFFFFF9F2),
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: Row(
                    children: [
                      Expanded(
                        child: _AnomalyMetric(
                          label: alert.isServerAlert ? '감지 횟수' : '최근 20분',
                          value: '${alert.currentCount}회',
                        ),
                      ),
                      if (hasNormalRange) ...[
                        const SizedBox(
                          height: 32,
                          child: VerticalDivider(color: Color(0xFFE5D7C7)),
                        ),
                        Expanded(
                          child: _AnomalyMetric(
                            label: '평소 범위',
                            value: '${alert.normalMin}~${alert.normalMax}회',
                          ),
                        ),
                      ],
                    ],
                  ),
                ),
                const SizedBox(height: 13),
              ],
              Row(
                children: [
                  Expanded(
                    child: OutlinedButton(
                      onPressed: () => _showAlertDetail(alert),
                      child: const Text('상세 보기'),
                    ),
                  ),
                  const SizedBox(width: 10),
                  Expanded(
                    child: FilledButton.icon(
                      onPressed:
                          _updatingAnomalyPause ||
                              _snapshot?.repetitiveAlertPauseAvailable != true
                          ? null
                          : () => _showAnomalyPauseSheet(context),
                      icon: const Icon(Icons.check_circle_outline_rounded),
                      label: const Text('정상으로 확인'),
                    ),
                  ),
                ],
              ),
            ],
          ],
        ),
      ),
    );
  }

  Widget _buildAlertCard(List<GuardianAlert> alerts) {
    final first = alerts[0];
    final second = alerts[1];

    return Card(
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.all(Radius.circular(20)),
      ),
      child: Column(
        children: [
          _AlertTile(
            icon: _alertIcon(first.type),
            iconColor: _alertColor(first.type),
            iconBackground: _alertBackground(first.type),
            title: first.title,
            subtitle: first.timeLabel,
            onTap: () => _showAlertDetail(first),
          ),
          const Divider(height: 1, indent: 72, color: Color(0xFFE8ECEA)),
          _AlertTile(
            icon: _alertIcon(second.type),
            iconColor: _alertColor(second.type),
            iconBackground: _alertBackground(second.type),
            title: second.title,
            subtitle: second.timeLabel,
            onTap: () => _showAlertDetail(second),
          ),
        ],
      ),
    );
  }

  Widget _buildVoiceTrainingHomeCard(BuildContext context) {
    final progress = _voiceTrainingProgress;

    if (_voiceTrainingLoadError != null) {
      return Card(
        color: const Color(0xFFFFF6E8),
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: Color(0xFFF0D9B7)),
        ),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Row(
            children: [
              const Icon(Icons.mic_off_outlined, color: Color(0xFF9A6625)),
              const SizedBox(width: 12),
              const Expanded(
                child: Text(
                  '음성 학습 진행률을 불러오지 못했어요',
                  style: TextStyle(color: _dark, fontWeight: FontWeight.w800),
                ),
              ),
              TextButton(
                onPressed: _loadVoiceTrainingProgress,
                child: const Text('다시 시도'),
              ),
            ],
          ),
        ),
      );
    }

    if (progress == null) {
      return const Card(
        color: Color(0xFFF2F7F5),
        elevation: 0,
        child: Padding(
          padding: EdgeInsets.all(22),
          child: Row(
            children: [
              SizedBox(
                width: 22,
                height: 22,
                child: CircularProgressIndicator(strokeWidth: 2.5),
              ),
              SizedBox(width: 14),
              Text(
                '음성 학습 준비 상태를 확인하고 있어요',
                style: TextStyle(color: _dark, fontWeight: FontWeight.w700),
              ),
            ],
          ),
        ),
      );
    }

    if (!progress.canRecord) {
      return Card(
        color: const Color(0xFFEAF5F0),
        child: Padding(
          padding: const EdgeInsets.all(18),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                progress.statusLabel,
                style: const TextStyle(
                  color: _dark,
                  fontSize: 17,
                  fontWeight: FontWeight.w900,
                ),
              ),
              const SizedBox(height: 8),
              Text(
                '${progress.clipCount}개 문장 · ${progress.recordedSeconds}초 녹음',
                style: const TextStyle(color: _muted),
              ),
              const SizedBox(height: 8),
              const Text(
                '이전에 학습한 목소리와 녹음은 유지됩니다.',
                style: TextStyle(color: _muted),
              ),
              TextButton.icon(
                onPressed: () => _showVoiceRecordingSheet(context),
                icon: const Icon(Icons.record_voice_over_outlined),
                label: const Text('음성 학습 관리'),
              ),
            ],
          ),
        ),
      );
    }

    if (progress.isReady) {
      return Card(
        color: const Color(0xFFEAF5F0),
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(20),
          side: const BorderSide(color: Color(0xFFC6E1D5)),
        ),
        child: Padding(
          padding: const EdgeInsets.fromLTRB(18, 16, 12, 16),
          child: Row(
            children: [
              const CircleAvatar(
                backgroundColor: _green,
                foregroundColor: Colors.white,
                child: Icon(Icons.check_rounded),
              ),
              const SizedBox(width: 13),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      '권장 녹음 분량 달성',
                      style: TextStyle(
                        color: _dark,
                        fontSize: 16,
                        fontWeight: FontWeight.w900,
                      ),
                    ),
                    const SizedBox(height: 3),
                    Text(
                      '${progress.recordedSeconds}초 녹음됨 · 더 녹음하면 TTS 품질이 높아져요.',
                      style: const TextStyle(color: _muted, fontSize: 13),
                    ),
                  ],
                ),
              ),
              TextButton(
                onPressed: () => _showVoiceRecordingSheet(context),
                child: const Text('추가 녹음'),
              ),
            ],
          ),
        ),
      );
    }

    final actionLabel = progress.recordedSeconds == 0 ? '학습 시작' : '이어서 녹음';
    return Card(
      color: const Color(0xFFEAF5F0),
      elevation: 0,
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(22),
        side: const BorderSide(color: Color(0xFFBFDCCC)),
      ),
      child: Padding(
        padding: const EdgeInsets.all(20),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Row(
              children: [
                CircleAvatar(
                  backgroundColor: _green,
                  foregroundColor: Colors.white,
                  child: Icon(Icons.mic_rounded),
                ),
                SizedBox(width: 12),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        '가장 먼저 설정해 주세요',
                        style: TextStyle(
                          color: _green,
                          fontSize: 12,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                      SizedBox(height: 2),
                      Text(
                        '보호자 목소리 학습이 필요해요',
                        style: TextStyle(
                          color: _dark,
                          fontSize: 18,
                          fontWeight: FontWeight.w900,
                        ),
                      ),
                    ],
                  ),
                ),
              ],
            ),
            const SizedBox(height: 14),
            const Text(
              '자연스러운 TTS를 위해 800초 녹음을 권장합니다. 권장 시간을 넘겨도 계속 녹음할 수 있어요.',
              style: TextStyle(color: _muted, height: 1.45),
            ),
            const SizedBox(height: 16),
            Row(
              children: [
                Text(
                  '${progress.recordedSeconds} / ${progress.targetSeconds}초 권장',
                  style: const TextStyle(
                    color: _dark,
                    fontSize: 15,
                    fontWeight: FontWeight.w900,
                  ),
                ),
                const Spacer(),
                Text(
                  '클립 ${progress.clipCount}개 · 권장까지 ${_trainingDurationLabel(progress.remainingSeconds)} 남음',
                  style: const TextStyle(color: _muted, fontSize: 12),
                ),
              ],
            ),
            const SizedBox(height: 8),
            ClipRRect(
              borderRadius: BorderRadius.circular(99),
              child: LinearProgressIndicator(
                value: progress.fraction,
                minHeight: 8,
                backgroundColor: Colors.white,
                color: _green,
              ),
            ),
            const SizedBox(height: 17),
            SizedBox(
              width: double.infinity,
              child: FilledButton.icon(
                onPressed: () => _showVoiceRecordingSheet(context),
                icon: const Icon(Icons.mic_none_rounded),
                label: Text(actionLabel),
              ),
            ),
            const SizedBox(height: 10),
            const Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Icon(Icons.info_outline_rounded, size: 16, color: _muted),
                SizedBox(width: 6),
                Expanded(
                  child: Text(
                    '800초는 권장 기준이며 녹음이 많을수록 TTS 품질 향상에 도움이 돼요.',
                    style: TextStyle(color: _muted, fontSize: 12),
                  ),
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }

  String _trainingDurationLabel(int seconds) {
    final minutes = seconds ~/ 60;
    final remainingSeconds = seconds % 60;
    if (minutes == 0) return '$remainingSeconds초';
    if (remainingSeconds == 0) return '$minutes분';
    return '$minutes분 $remainingSeconds초';
  }

  Widget _buildQuickActions(BuildContext context) {
    return _QuickAction(
      icon: Icons.phone_outlined,
      label: '전화 걸기',
      onTap: _requestCareCall,
    );
  }

  Widget _buildEmergencyButton(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      height: 54,
      child: FilledButton.icon(
        onPressed: _requestEmergencyContact,
        style: FilledButton.styleFrom(
          backgroundColor: const Color(0xFFB53E3E),
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(16),
          ),
        ),
        icon: const Icon(Icons.sos_rounded),
        label: const Text(
          '긴급 연락',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.w800),
        ),
      ),
    );
  }
}
