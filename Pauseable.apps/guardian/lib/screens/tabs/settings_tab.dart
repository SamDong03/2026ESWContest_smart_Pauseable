part of '../guardian_home_page.dart';

class _SettingsTab extends StatefulWidget {
  const _SettingsTab({
    required this.repository,
    required this.onPreferencesChanged,
    required this.webPushClient,
    required this.nativePushClient,
    required this.profile,
    required this.loadingProfile,
    required this.profileLoadFailed,
    required this.onEditProfile,
    required this.onRetryProfile,
    required this.activeScenario,
    required this.applyingScenario,
    required this.onScenarioSelected,
    required this.themeMode,
    required this.onThemeModeChanged,
    required this.homeEnvironment,
    required this.onHomeEnvironmentChanged,
  });

  final GuardianRepository repository;
  final ValueChanged<GuardianPreferences> onPreferencesChanged;
  final WebPushClient? webPushClient;
  final NativePushClient? nativePushClient;
  final GuardianProfile? profile;
  final bool loadingProfile;
  final bool profileLoadFailed;
  final VoidCallback onEditProfile;
  final VoidCallback onRetryProfile;
  final DemoScenario activeScenario;
  final DemoScenario? applyingScenario;
  final ValueChanged<DemoScenario> onScenarioSelected;
  final ThemeMode themeMode;
  final ValueChanged<ThemeMode> onThemeModeChanged;
  final HomeEnvironment? homeEnvironment;
  final ValueChanged<HomeEnvironment> onHomeEnvironmentChanged;

  @override
  State<_SettingsTab> createState() => _SettingsTabState();
}

class _SettingsTabState extends State<_SettingsTab> {
  WebPushState? _webPushState;
  bool _loadingWebPush = false;
  bool _updatingWebPush = false;
  bool _webPushLoadFailed = false;
  String? _webPushTestId;
  bool _sendingWebPushTest = false;

  Future<void> _sendWebPushTest() async {
    final client = widget.webPushClient;
    if (client == null || _sendingWebPushTest) return;
    setState(() => _sendingWebPushTest = true);
    String message;
    try {
      final testId = await client.scheduleTest();
      if (mounted) setState(() => _webPushTestId = testId);
      message = '시험 알림을 예약했어요. Chrome은 켜 둔 채 이 앱 탭만 닫고 10초 정도 기다려 주세요. 실제 위험 상황이 아닙니다.';
    } catch (_) {
      message = '시험 알림을 예약하지 못했습니다. 구독·서버 연결을 확인하거나, 직전 시험 후 30초를 기다려 주세요.';
    }
    if (!mounted) return;
    setState(() => _sendingWebPushTest = false);
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(duration: const Duration(seconds: 15), content: Text(message)),
    );
  }

  Future<void> _checkWebPushTest() async {
    final testId = _webPushTestId;
    final client = widget.webPushClient;
    if (client == null || testId == null || _sendingWebPushTest) return;
    setState(() => _sendingWebPushTest = true);
    String message;
    try {
      final status = await client.testResult(testId);
      message = switch (status) {
        'scheduled' => '아직 발송 대기 중입니다. 잠시 후 다시 확인해 주세요.',
        'accepted' => '푸시 서비스가 시험 알림을 수락했습니다. 실제 화면에 표시됐는지는 알림창에서 확인해 주세요.',
        'skipped' => '브라우저 구독이 해제되었거나 서버 설정이 바뀌어 발송하지 않았습니다.',
        _ => '시험 알림 전송에 실패했습니다. 구독과 서버 설정을 확인해 주세요.',
      };
    } catch (_) {
      message = '시험 결과가 만료됐거나 조회할 수 없습니다. 연결 후 다시 시험해 주세요.';
    }
    if (!mounted) return;
    setState(() => _sendingWebPushTest = false);
    ScaffoldMessenger.of(context).hideCurrentSnackBar();
    ScaffoldMessenger.of(context)
        .showSnackBar(SnackBar(content: Text(message)));
  }

  void _nativePushChanged() {
    if (mounted) setState(() {});
  }

  String _nativePushDescription(NativePushClient client) =>
      switch (client.status) {
        NativePushStatus.checking => '휴대폰 알림 연결을 확인하는 중입니다.',
        NativePushStatus.unsupported => 'Android 앱에서 사용할 수 있습니다.',
        NativePushStatus.authenticationMissing =>
          '앱의 서버 인증 설정이 없습니다. 연결 설정을 포함한 새 APK를 설치해 주세요.',
        NativePushStatus.authenticationRejected =>
          '앱의 서버 인증을 확인해야 합니다. 팀원에게 새 APK를 요청해 주세요.',
        NativePushStatus.firebaseNotConfigured =>
          '이 APK의 휴대폰 알림 설정이 없습니다. 알림 설정을 포함한 새 APK를 설치해 주세요.',
        NativePushStatus.serverNotConfigured => '서버의 휴대폰 알림 연결이 아직 완료되지 않았습니다.',
        NativePushStatus.permissionRequired => '알림을 허용하면 앱을 닫아도 알림을 받습니다.',
        NativePushStatus.permissionDenied =>
          '휴대폰 알림 설정에서 이 앱과 보호자 안전 알림을 허용해 주세요.',
        NativePushStatus.tokenUnavailable =>
          '휴대폰 알림 연결을 만들지 못했습니다. 인터넷과 Google Play 서비스를 확인해 주세요.',
        NativePushStatus.connectionFailed =>
          '서버 연결에 실패했습니다. 인터넷 연결을 확인한 뒤 다시 시도해 주세요.',
        NativePushStatus.registered =>
          _preferencesLoadFailed
              ? '기기 연결 완료 · 안전 알림 설정을 다시 확인해 주세요.'
              : !_safetyNotifications
              ? '기기 연결 완료 · 안전 이상 알림은 꺼져 있어요. 직접 누르는 시험 알림은 별도입니다.'
              : '연결 완료 · 앱을 닫아도 안전 알림을 받습니다. 알림을 누르면 알림 목록을 엽니다.',
      };

  Future<void> _sendNativePushTest() async {
    final client = widget.nativePushClient;
    if (client == null) return;
    ScaffoldMessenger.of(context).showSnackBar(
      const SnackBar(
        duration: Duration(seconds: 12),
        content: Text('10초 뒤 시험 알림이 옵니다. 홈 버튼을 누르거나 화면을 잠가 확인하세요.'),
      ),
    );
    String message;
    try {
      final result = await client.sendTest();
      message = result.accepted > 0
          ? '시험 알림을 전송했습니다. 휴대폰 알림창에서 수신을 확인해 주세요.'
          : '시험 알림을 전송하지 못했습니다. 휴대폰 알림 연결을 다시 확인해 주세요.';
    } catch (_) {
      message = '시험 알림을 보내지 못했습니다. 연결 상태를 다시 확인해 주세요.';
    }
    if (mounted) {
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text(message)));
    }
  }

  Future<void> _openNativeNotificationSettings() async {
    try {
      await widget.nativePushClient?.openNotificationSettings();
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('휴대폰 설정에서 이 앱의 알림을 허용해 주세요.')),
        );
      }
    }
  }

  Widget _nativePushTile(NativePushClient client) => Padding(
    padding: const EdgeInsets.fromLTRB(16, 12, 16, 12),
    child: Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ListTile(
          contentPadding: EdgeInsets.zero,
          leading: const Icon(Icons.notifications_active_outlined),
          title: const Text('휴대폰 알림'),
          subtitle: Text(_nativePushDescription(client)),
        ),
        Wrap(
          spacing: 8,
          children: [
            TextButton(
              onPressed: client.busy
                  ? null
                  : () => unawaited(client.refresh(requestPermission: true)),
              child: Text(
                client.status == NativePushStatus.permissionRequired
                    ? '알림 허용'
                    : '재시도',
              ),
            ),
            if (client.status == NativePushStatus.permissionDenied ||
                client.status == NativePushStatus.registered)
              TextButton(
                onPressed: client.busy ? null : _openNativeNotificationSettings,
                child: const Text('휴대폰 알림 설정'),
              ),
            if (client.status == NativePushStatus.registered)
              FilledButton.tonal(
                onPressed: client.canSendTest ? _sendNativePushTest : null,
                child: const Text('시험 알림 보내기'),
              ),
          ],
        ),
      ],
    ),
  );

  Future<void> _loadWebPush() async {
    final client = widget.webPushClient;
    if (client == null) return;
    setState(() {
      _loadingWebPush = true;
      _webPushLoadFailed = false;
    });
    try {
      final state = await client.loadState();
      if (mounted) setState(() => _webPushState = state);
    } catch (_) {
      if (mounted) setState(() => _webPushLoadFailed = true);
    } finally {
      if (mounted) setState(() => _loadingWebPush = false);
    }
  }

  Future<void> _enableWebPush() async {
    final client = widget.webPushClient;
    final key = _webPushState?.publicKey;
    if (client == null || key == null || _updatingWebPush) return;
    setState(() => _updatingWebPush = true);
    try {
      await client.enable(key);
      await _loadWebPush();
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('이 브라우저에서 웹 푸시 알림을 받습니다.')),
        );
      }
    } catch (error) {
      if (mounted) {
        final detail = error
            .toString()
            .replaceAll(RegExp(r'https?://\S+'), '[주소]')
            .replaceAll(RegExp(r'Bearer\s+\S+'), 'Bearer [숨김]');
        final shortDetail = detail.length > 180
            ? '${detail.substring(0, 180)}…'
            : detail;
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            duration: const Duration(seconds: 12),
            content: Text('웹 푸시를 켜지 못했습니다: $shortDetail'),
          ),
        );
      }
    } finally {
      if (mounted) setState(() => _updatingWebPush = false);
    }
  }

  Future<void> _disableWebPush() async {
    final client = widget.webPushClient;
    if (client == null || _updatingWebPush) return;
    setState(() => _updatingWebPush = true);
    try {
      await client.disable();
      await _loadWebPush();
      if (mounted) {
        ScaffoldMessenger.of(context)
            .showSnackBar(const SnackBar(content: Text('이 브라우저의 웹 푸시를 껐습니다.')));
      }
    } catch (_) {
      if (mounted) {
        ScaffoldMessenger.of(context).showSnackBar(
          const SnackBar(content: Text('웹 푸시 해제에 실패했습니다. 다시 시도해 주세요.')),
        );
      }
    } finally {
      if (mounted) setState(() => _updatingWebPush = false);
    }
  }

  Future<void> _editHomeEnvironment() async {
    HomeEnvironment initial;
    try {
      initial = await widget.repository.loadHomeEnvironment();
    } catch (_) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('거주 지역 설정을 불러오지 못했습니다. 다시 시도해 주세요.')),
      );
      return;
    }
    if (!mounted) return;
    final saved = await Navigator.of(context).push<HomeEnvironment>(
      MaterialPageRoute(
        builder: (pageContext) => HomeRegionPage(
          repository: widget.repository,
          initial: initial,
          onSaved: (value) => Navigator.of(pageContext).pop(value),
        ),
      ),
    );
    if (saved != null && mounted) widget.onHomeEnvironmentChanged(saved);
  }

  bool _safetyNotifications = true;
  bool _soundEnabled = false;
  bool _loadingSettings = true;
  bool _preferencesLoadFailed = false;
  bool _savingPreferences = false;

  @override
  void initState() {
    super.initState();
    _loadSettings();
    _loadWebPush();
    widget.nativePushClient?.addListener(_nativePushChanged);
  }

  @override
  void didUpdateWidget(covariant _SettingsTab oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (!identical(oldWidget.nativePushClient, widget.nativePushClient)) {
      oldWidget.nativePushClient?.removeListener(_nativePushChanged);
      widget.nativePushClient?.addListener(_nativePushChanged);
    }
  }

  @override
  void dispose() {
    widget.nativePushClient?.removeListener(_nativePushChanged);
    super.dispose();
  }

  Future<void> _loadSettings() async {
    setState(() {
      _loadingSettings = true;
      _preferencesLoadFailed = false;
    });

    await _loadPreferences();
    if (mounted) setState(() => _loadingSettings = false);
  }

  Future<void> _loadPreferences() async {
    try {
      final preferences = await widget.repository.loadPreferences();
      if (!mounted) return;
      setState(() {
        _safetyNotifications = preferences.safetyNotifications;
        _soundEnabled = preferences.soundEnabled;
      });
      widget.onPreferencesChanged(preferences);
    } catch (_) {
      if (!mounted) return;
      setState(() => _preferencesLoadFailed = true);
    }
  }

  Future<void> _updatePreferences({
    bool? safetyNotifications,
    bool? soundEnabled,
  }) async {
    if (_loadingSettings || _preferencesLoadFailed || _savingPreferences) {
      return;
    }
    final previousSafety = _safetyNotifications;
    final previousSound = _soundEnabled;
    final nextSafety = safetyNotifications ?? _safetyNotifications;
    final nextSound = soundEnabled ?? _soundEnabled;
    setState(() {
      _safetyNotifications = nextSafety;
      _soundEnabled = nextSound;
      _savingPreferences = true;
    });

    try {
      final saved = await widget.repository.updatePreferences(
        safetyNotifications: nextSafety,
        soundEnabled: nextSound,
      );
      if (!mounted) return;
      setState(() {
        _safetyNotifications = saved.safetyNotifications;
        _soundEnabled = saved.soundEnabled;
      });
      widget.onPreferencesChanged(saved);
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('알림 설정을 저장했습니다.')));
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _safetyNotifications = previousSafety;
        _soundEnabled = previousSound;
      });
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('알림 설정을 저장하지 못했습니다.')));
    } finally {
      if (mounted) setState(() => _savingPreferences = false);
    }
  }

  Future<void> _showAppInfo() async {
    showAboutDialog(
      context: context,
      applicationName: 'PAUSEABLE 보호자',
      applicationVersion: '1.0.0 (데모)',
      applicationIcon: const CircleAvatar(
        backgroundColor: _green,
        foregroundColor: Colors.white,
        child: Text('P', style: TextStyle(fontWeight: FontWeight.w900)),
      ),
      children: const [
        Text('알림·출입 사진 확인과 돌봄 설정을 지원하는 대회 시연 버전입니다. 데모 상황 시뮬레이터는 실제 감지와 별개입니다.'),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    return _TabFrame(
      title: '앱 설정',
      subtitle: '보호자 정보와 알림 방식을 관리하세요.',
      children: [
        Card(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
          ),
          child: Column(
            children: [
              ListTile(
                onTap: widget.loadingProfile || widget.profileLoadFailed
                    ? null
                    : widget.onEditProfile,
                leading: const Icon(Icons.person_outline_rounded),
                title: Text(
                  widget.loadingProfile
                      ? '불러오는 중…'
                      : widget.profile?.guardianLabel ?? '보호자님',
                  style: const TextStyle(fontWeight: FontWeight.w800),
                ),
                subtitle: const Text('보호자 정보'),
                trailing: const Icon(Icons.edit_outlined),
              ),
              const Divider(height: 1, indent: 56),
              ListTile(
                onTap: widget.loadingProfile || widget.profileLoadFailed
                    ? null
                    : widget.onEditProfile,
                leading: const Icon(Icons.favorite_border_rounded),
                title: Text(widget.profile?.patientLabel ?? '돌봄 대상자'),
                subtitle: Text(
                  widget.profile?.relationship.trim().isNotEmpty == true
                      ? '대상자와의 관계 · ${widget.profile!.relationship}'
                      : '이름을 등록하고 돌봄 정보를 관리하세요.',
                ),
                trailing: const Icon(Icons.chevron_right_rounded),
              ),
              const Divider(height: 1, indent: 56),
              ListTile(
                key: const ValueKey('family-tts-settings'),
                onTap: widget.loadingProfile || widget.profileLoadFailed
                    ? null
                    : widget.onEditProfile,
                leading: const Icon(Icons.record_voice_over_outlined),
                title: const Text('가족관계·TTS 호칭'),
                subtitle: Text(
                  widget.profile?.patientCallName.trim().isNotEmpty == true
                      ? '부르는 호칭 · ${widget.profile!.patientCallName}'
                      : '엄마, 아빠, 할머니 등 익숙한 호칭을 설정하세요.',
                ),
                trailing: const Icon(Icons.edit_outlined),
              ),
              if (widget.profileLoadFailed)
                ListTile(
                  title: const Text('돌봄 정보를 불러오지 못했습니다.'),
                  trailing: TextButton(
                    onPressed: widget.onRetryProfile,
                    child: const Text('재시도'),
                  ),
                ),
            ],
          ),
        ),
        const SizedBox(height: 24),
        Text(
          '화면 설정',
          style: TextStyle(
            color: _primaryText(context),
            fontSize: 18,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 12),
        Card(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
          ),
          child: Padding(
            padding: const EdgeInsets.all(18),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(
                      widget.themeMode == ThemeMode.dark
                          ? Icons.dark_mode_outlined
                          : Icons.light_mode_outlined,
                    ),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Text(
                        '앱 테마',
                        style: TextStyle(fontWeight: FontWeight.w800),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Text(
                  '눈이 편한 화면 모드를 선택하세요.',
                  style: TextStyle(color: _secondaryText(context)),
                ),
                const SizedBox(height: 16),
                SizedBox(
                  width: double.infinity,
                  child: SegmentedButton<ThemeMode>(
                    segments: const [
                      ButtonSegment(
                        value: ThemeMode.light,
                        icon: Icon(Icons.light_mode_outlined),
                        label: Text('라이트 모드'),
                      ),
                      ButtonSegment(
                        value: ThemeMode.dark,
                        icon: Icon(Icons.dark_mode_outlined),
                        label: Text('다크 모드'),
                      ),
                    ],
                    selected: {widget.themeMode},
                    showSelectedIcon: true,
                    onSelectionChanged: (selection) {
                      widget.onThemeModeChanged(selection.first);
                    },
                  ),
                ),
              ],
            ),
          ),
        ),
        const SizedBox(height: 24),
        Text(
          '자동 조명용 거주 지역',
          style: TextStyle(
            color: _primaryText(context),
            fontSize: 18,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 12),
        Card(
          child: ListTile(
            leading: const Icon(Icons.home_outlined),
            title: Text(widget.homeEnvironment?.region?.label ?? '거주 지역 설정 필요'),
            subtitle: Text(
              widget.homeEnvironment?.statusLabel ?? '연결을 확인한 뒤 지역을 설정해 주세요',
            ),
            trailing: const Icon(Icons.chevron_right),
            onTap: _editHomeEnvironment,
          ),
        ),
        const SizedBox(height: 24),
        Text(
          '멀티미디어',
          style: TextStyle(
            color: _primaryText(context),
            fontSize: 18,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 12),
        Card(
          child: ListTile(
            leading: const Icon(Icons.music_note_rounded),
            title: const Text('환자가 좋아하는 노래'),
            subtitle: const Text('반복행동·배회 시 재생할 유튜브 링크 관리'),
            trailing: const Icon(Icons.chevron_right_rounded),
            onTap: () => Navigator.of(context).push(
              MaterialPageRoute(
                builder: (_) =>
                    FavoriteSongsPage(repository: widget.repository),
              ),
            ),
          ),
        ),
        const SizedBox(height: 24),
        Text(
          '데모 상황 시뮬레이터',
          style: TextStyle(
            color: _primaryText(context),
            fontSize: 18,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 6),
        Text(
          '실제 센서 연결 전 가짜 상황을 발생시켜 앱 전체 흐름을 확인합니다.',
          style: TextStyle(color: _secondaryText(context), height: 1.4),
        ),
        const SizedBox(height: 12),
        Card(
          clipBehavior: Clip.antiAlias,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
          ),
          child: Column(
            children: [
              Container(
                width: double.infinity,
                padding: const EdgeInsets.all(16),
                color: _softSurface(context),
                child: Row(
                  children: [
                    const Icon(Icons.science_outlined, color: _green),
                    const SizedBox(width: 10),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Text(
                            '현재 실행 중인 상황',
                            style: TextStyle(
                              color: _secondaryText(context),
                              fontSize: 12,
                            ),
                          ),
                          const SizedBox(height: 2),
                          Text(
                            widget.activeScenario.label,
                            style: TextStyle(
                              color: _primaryText(context),
                              fontSize: 16,
                              fontWeight: FontWeight.w900,
                            ),
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),
              for (
                var index = 0;
                index < DemoScenario.values.length;
                index++
              ) ...[
                _DemoScenarioTile(
                  scenario: DemoScenario.values[index],
                  selected: widget.activeScenario == DemoScenario.values[index],
                  applying:
                      widget.applyingScenario == DemoScenario.values[index],
                  enabled: widget.applyingScenario == null,
                  onTap: () =>
                      widget.onScenarioSelected(DemoScenario.values[index]),
                ),
                if (index < DemoScenario.values.length - 1)
                  const Divider(height: 1, indent: 58),
              ],
            ],
          ),
        ),
        const SizedBox(height: 10),
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Icon(
              Icons.info_outline_rounded,
              color: _secondaryText(context),
              size: 17,
            ),
            const SizedBox(width: 7),
            Expanded(
              child: Text(
                '상황을 바꾸면 홈과 알림 데이터가 즉시 갱신됩니다. 실제 장비 연결 후에는 이 메뉴를 숨길 수 있습니다.',
                style: TextStyle(
                  color: _secondaryText(context),
                  fontSize: 12,
                  height: 1.4,
                ),
              ),
            ),
          ],
        ),
        const SizedBox(height: 24),
        Text(
          '알림 설정',
          style: TextStyle(
            color: _primaryText(context),
            fontSize: 18,
            fontWeight: FontWeight.w800,
          ),
        ),
        const SizedBox(height: 12),
        Card(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
          ),
          child: Column(
            children: [
              SwitchListTile(
                value: _safetyNotifications,
                onChanged:
                    _loadingSettings ||
                        _preferencesLoadFailed ||
                        _savingPreferences
                    ? null
                    : (value) => _updatePreferences(safetyNotifications: value),
                secondary: const Icon(Icons.shield_outlined),
                title: const Text('안전 이상 알림'),
                subtitle: const Text('웹·휴대폰 푸시를 함께 설정해요. 꺼도 기록·사진은 저장됩니다.'),
              ),
              const Divider(height: 1, indent: 56),
              SwitchListTile(
                value: _soundEnabled,
                onChanged:
                    _loadingSettings ||
                        _preferencesLoadFailed ||
                        _savingPreferences
                    ? null
                    : (value) => _updatePreferences(soundEnabled: value),
                secondary: const Icon(Icons.volume_up_outlined),
                title: const Text('알림음'),
                subtitle: const Text('끄면 무음으로 요청합니다. 기기·브라우저의 소리 설정이 우선해요.'),
              ),
              const Divider(height: 1, indent: 56),
              if (_preferencesLoadFailed)
                ListTile(
                  title: const Text('알림 설정을 불러오지 못했어요'),
                  subtitle: const Text('기존 설정을 보호하기 위해 변경을 잠시 막았습니다.'),
                  trailing: TextButton(
                    onPressed: _loadingSettings ? null : _loadSettings,
                    child: const Text('설정 재시도'),
                  ),
                ),
              if (widget.nativePushClient?.supported == true)
                _nativePushTile(widget.nativePushClient!)
              else ...[
                ListTile(
                  leading: const Icon(Icons.notifications_active_outlined),
                  title: const Text('웹 푸시 알림'),
                  subtitle: Text(
                    widget.webPushClient == null ||
                            _webPushState?.browserSupported == false
                        ? '웹 브라우저에서만 사용할 수 있습니다.'
                        : _loadingWebPush
                        ? '알림 상태를 확인하는 중입니다.'
                        : _webPushLoadFailed
                        ? '서버 연결을 확인해 주세요.'
                        : _webPushState?.serverEnabled == false
                        ? '서버의 푸시 설정이 아직 완료되지 않았습니다.'
                        : _webPushState?.permission == 'denied'
                        ? '브라우저 설정에서 이 사이트의 알림을 허용해 주세요.'
                        : _webPushState?.subscribed == true
                        ? _preferencesLoadFailed
                              ? '브라우저 연결 완료 · 안전 알림 설정을 다시 확인해 주세요.'
                              : !_safetyNotifications
                              ? '브라우저 연결 완료 · 안전 이상 알림은 꺼져 있어요. 시험 알림은 별도입니다.'
                              : '앱을 닫아도 이 브라우저에 알림을 보냅니다.'
                        : '반복행동·배회 감지 시 브라우저 밖에서도 알림을 받습니다.',
                  ),
                  trailing: _webPushLoadFailed
                      ? TextButton(
                          onPressed: _loadingWebPush ? null : _loadWebPush,
                          child: const Text('재시도'),
                        )
                      : _webPushState?.browserSupported == true &&
                            (_webPushState?.subscribed == true ||
                                (_webPushState?.serverEnabled == true &&
                                    _webPushState?.permission != 'denied'))
                      ? TextButton(
                          onPressed: _updatingWebPush
                              ? null
                              : _webPushState!.subscribed
                              ? _disableWebPush
                              : _enableWebPush,
                          child: Text(_webPushState!.subscribed ? '끄기' : '켜기'),
                        )
                      : null,
                ),
                if (_webPushState?.serverEnabled == true &&
                    _webPushState?.subscribed == true)
                  Padding(
                    padding: const EdgeInsets.fromLTRB(56, 0, 16, 12),
                    child: Wrap(
                      spacing: 8,
                      children: [
                        FilledButton.tonal(
                          onPressed: _sendingWebPushTest || _updatingWebPush
                              ? null
                              : _sendWebPushTest,
                          child: const Text('10초 후 시험 알림'),
                        ),
                        if (_webPushTestId != null)
                          TextButton(
                            onPressed: _sendingWebPushTest
                                ? null
                                : _checkWebPushTest,
                            child: const Text('전송 결과 확인'),
                          ),
                      ],
                    ),
                  ),
              ],
            ],
          ),
        ),
        const SizedBox(height: 16),
        Card(
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
          ),
          child: Column(
            children: [
              ListTile(
                onTap: _showAppInfo,
                leading: const Icon(Icons.info_outline_rounded),
                title: const Text('앱 정보'),
                subtitle: const Text('버전 1.0.0 · 대회 시연 버전'),
                trailing: const Icon(Icons.chevron_right_rounded),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _DemoScenarioTile extends StatelessWidget {
  const _DemoScenarioTile({
    required this.scenario,
    required this.selected,
    required this.applying,
    required this.enabled,
    required this.onTap,
  });

  final DemoScenario scenario;
  final bool selected;
  final bool applying;
  final bool enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      enabled: enabled,
      selected: selected,
      selectedTileColor: _softSurface(context),
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 4),
      leading: CircleAvatar(
        backgroundColor: selected
            ? Theme.of(context).colorScheme.primaryContainer
            : _softSurface(context),
        foregroundColor: selected ? _green : _secondaryText(context),
        child: Icon(_demoScenarioIcon(scenario), size: 21),
      ),
      title: Text(
        scenario.label,
        style: TextStyle(
          color: _primaryText(context),
          fontWeight: selected ? FontWeight.w900 : FontWeight.w700,
        ),
      ),
      subtitle: Text(scenario.description),
      trailing: applying
          ? const SizedBox.square(
              dimension: 20,
              child: CircularProgressIndicator(strokeWidth: 2.5),
            )
          : selected
          ? const Icon(Icons.check_circle_rounded, color: _green)
          : const Icon(Icons.chevron_right_rounded),
      onTap: enabled ? onTap : null,
    );
  }
}

IconData _demoScenarioIcon(DemoScenario scenario) => switch (scenario) {
  DemoScenario.normal => Icons.verified_outlined,
  DemoScenario.repetitiveBehavior => Icons.repeat_rounded,
  DemoScenario.inactivity => Icons.motion_photos_off_outlined,
  DemoScenario.nightMovement => Icons.nights_stay_outlined,
  DemoScenario.doorExit => Icons.camera_alt_outlined,
};
