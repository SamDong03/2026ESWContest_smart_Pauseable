import 'dart:async';

import 'package:flutter/material.dart';

import 'repositories/guardian_repository.dart';
import 'screens/guardian_home_page.dart';
import 'services/live_alert_client.dart';
import 'services/native_push_client.dart';
import 'services/web_push_client.dart';
import 'services/voice_recording_service.dart';
import 'models/home_environment.dart';
import 'screens/home_region_page.dart';

class PauseableApp extends StatefulWidget {
  const PauseableApp({
    super.key,
    required this.repository,
    this.liveAlertClient,
    this.webPushClient,
    this.nativePushClient,
    this.voiceRecorderFactory,
  });

  final GuardianRepository repository;
  final LiveAlertClient? liveAlertClient;
  final WebPushClient? webPushClient;
  final NativePushClient? nativePushClient;
  final VoiceRecorderFactory? voiceRecorderFactory;

  @override
  State<PauseableApp> createState() => _PauseableAppState();
}

class _PauseableAppState extends State<PauseableApp>
    with WidgetsBindingObserver {
  ThemeMode _themeMode = ThemeMode.light;
  HomeEnvironment? _environment;
  bool _loadingHome = true;
  bool _skipHomeSetup = false;
  bool _homeLoadFailed = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
    widget.nativePushClient?.addListener(_nativePushChanged);
    unawaited(
      widget.nativePushClient?.refresh(requestPermission: true) ??
          Future<void>.value(),
    );
    _loadHome();
  }

  void _nativePushChanged() {
    if (mounted &&
        widget.nativePushClient?.hasPendingNotificationOpen == true) {


      setState(() => _skipHomeSetup = true);
    }
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      unawaited(widget.nativePushClient?.refresh() ?? Future<void>.value());
    }
  }

  Future<void> _loadHome() async {
    setState(() {
      _loadingHome = true;
      _homeLoadFailed = false;
    });
    try {
      final result = await widget.repository.loadHomeEnvironment();
      if (mounted) setState(() => _environment = result);
    } catch (_) {
      if (mounted) setState(() => _homeLoadFailed = true);
    } finally {
      if (mounted) setState(() => _loadingHome = false);
    }
  }

  Widget _buildHome() {
    if (_loadingHome && !_skipHomeSetup) {
      return const Scaffold(body: Center(child: CircularProgressIndicator()));
    }
    if (_homeLoadFailed && !_skipHomeSetup) {
      return Scaffold(
        body: Center(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Text('거주 지역 설정을 불러오지 못했습니다.'),
              FilledButton(onPressed: _loadHome, child: const Text('다시 시도')),
              TextButton(
                onPressed: () => setState(() => _skipHomeSetup = true),
                child: const Text('홈으로 계속'),
              ),
            ],
          ),
        ),
      );
    }
    if (_environment?.region == null && !_skipHomeSetup) {
      return HomeRegionPage(
        repository: widget.repository,
        initial: _environment ?? const HomeEnvironment(),
        onSaved: (saved) => setState(() => _environment = saved),
        onSkip: () => setState(() => _skipHomeSetup = true),
      );
    }
    return GuardianHomePage(
      repository: widget.repository,
      liveAlertClient: widget.liveAlertClient,
      webPushClient: widget.webPushClient,
      nativePushClient: widget.nativePushClient,
      voiceRecorderFactory: widget.voiceRecorderFactory,
      themeMode: _themeMode,
      onThemeModeChanged: _changeThemeMode,
      homeEnvironment: _environment,
      onHomeEnvironmentChanged: (saved) => setState(() => _environment = saved),
    );
  }

  void _changeThemeMode(ThemeMode mode) {
    if (_themeMode == mode) return;
    setState(() => _themeMode = mode);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    widget.nativePushClient?.removeListener(_nativePushChanged);
    final liveAlertClient = widget.liveAlertClient;
    if (liveAlertClient != null) unawaited(liveAlertClient.dispose());
    widget.webPushClient?.dispose();
    widget.nativePushClient?.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'PAUSEABLE 보호자',
      debugShowCheckedModeBanner: false,
      theme: _buildTheme(Brightness.light),
      darkTheme: _buildTheme(Brightness.dark),
      themeMode: _themeMode,
      home: _buildHome(),
    );
  }

  ThemeData _buildTheme(Brightness brightness) {
    final isDark = brightness == Brightness.dark;
    final scheme = ColorScheme.fromSeed(
      seedColor: const Color(0xFF356B5A),
      brightness: brightness,
      surface: isDark ? const Color(0xFF18211E) : Colors.white,
    );

    return ThemeData(
      useMaterial3: true,
      brightness: brightness,
      colorScheme: scheme,
      scaffoldBackgroundColor: isDark
          ? const Color(0xFF101714)
          : const Color(0xFFF4F7F5),
      cardTheme: CardThemeData(
        elevation: 0,
        margin: EdgeInsets.zero,
        color: scheme.surface,
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: isDark ? const Color(0xFF18211E) : Colors.white,
        indicatorColor: isDark
            ? const Color(0xFF29483D)
            : const Color(0xFFDCEDE6),
      ),
      dividerTheme: DividerThemeData(
        color: scheme.outlineVariant.withValues(alpha: 0.65),
      ),
    );
  }
}
