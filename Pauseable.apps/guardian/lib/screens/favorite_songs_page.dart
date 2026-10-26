import 'package:flutter/material.dart';

import '../models/favorite_song.dart';
import '../repositories/guardian_repository.dart';

class FavoriteSongsPage extends StatefulWidget {
  const FavoriteSongsPage({super.key, required this.repository});

  final GuardianRepository repository;

  @override
  State<FavoriteSongsPage> createState() => _FavoriteSongsPageState();
}

class _FavoriteSongsPageState extends State<FavoriteSongsPage> {
  final _titleController = TextEditingController();
  final _urlController = TextEditingController();
  List<FavoriteSong> _songs = [];
  bool _loading = true;
  bool _saving = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _titleController.dispose();
    _urlController.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    setState(() {
      _loading = true;
      _error = null;
    });
    try {
      final songs = await widget.repository.loadFavoriteSongs();
      if (mounted) setState(() => _songs = songs);
    } catch (_) {
      if (mounted) setState(() => _error = '목록을 불러오지 못했습니다. 서버 연결을 확인해 주세요.');
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String? _videoId(String input) {
    final uri = Uri.tryParse(input.trim());
    if (uri == null || !['http', 'https'].contains(uri.scheme)) return null;
    final host = uri.host.toLowerCase();
    String? id;
    if (host == 'youtu.be' && uri.pathSegments.length == 1) {
      id = uri.pathSegments.first;
    } else if ({
      'youtube.com',
      'www.youtube.com',
      'm.youtube.com',
      'music.youtube.com',
    }.contains(host)) {
      if (uri.path == '/watch') {
        id = uri.queryParameters['v'];
      } else if (uri.pathSegments.length == 2 &&
          {'shorts', 'live'}.contains(uri.pathSegments.first)) {
        id = uri.pathSegments.last;
      }
    }
    return id != null && RegExp(r'^[A-Za-z0-9_-]{11}$').hasMatch(id)
        ? id
        : null;
  }

  Future<void> _save(List<FavoriteSong> proposed) async {
    setState(() {
      _saving = true;
      _error = null;
    });
    try {
      final saved = await widget.repository.saveFavoriteSongs(proposed);
      if (!mounted) return;
      setState(() => _songs = saved);
      _titleController.clear();
      _urlController.clear();
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('좋아하는 노래 목록을 저장했습니다.')));
    } catch (_) {
      if (mounted) setState(() => _error = '저장하지 못했습니다. 서버 연결과 링크를 확인해 주세요.');
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  void _add() {
    final title = _titleController.text.trim();
    final id = _videoId(_urlController.text);
    if (title.isEmpty || title.length > 80 || id == null) {
      setState(() => _error = '노래 이름과 유효한 유튜브 동영상 링크를 입력해 주세요.');
      return;
    }
    if (_songs.any((song) => song.videoId == id)) {
      setState(() => _error = '이미 등록한 동영상입니다.');
      return;
    }
    if (_songs.length >= 30) {
      setState(() => _error = '노래는 최대 30개까지 등록할 수 있습니다.');
      return;
    }
    _save([
      ..._songs,
      FavoriteSong(
        videoId: id,
        title: title,
        url: 'https://www.youtube.com/watch?v=$id',
      ),
    ]);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('좋아하는 노래')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(20),
          children: [
            const Text(
              '환자가 좋아하는 노래의 유튜브 동영상 링크를 등록해 주세요. '
              '반복행동·배회 상황에서 사용할 후보 목록입니다.',
            ),
            const SizedBox(height: 8),
            Text(
              '이 화면은 링크를 저장합니다. 실제 자동 재생은 멀티미디어 기기 연결 후 동작합니다.',
              style: TextStyle(
                color: Theme.of(context).colorScheme.onSurfaceVariant,
              ),
            ),
            const SizedBox(height: 20),
            TextField(
              controller: _titleController,
              maxLength: 80,
              decoration: const InputDecoration(
                labelText: '노래 이름',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 8),
            TextField(
              controller: _urlController,
              keyboardType: TextInputType.url,
              autocorrect: false,
              decoration: const InputDecoration(
                labelText: '유튜브 동영상 링크',
                hintText: 'https://www.youtube.com/watch?v=...',
                border: OutlineInputBorder(),
              ),
            ),
            const SizedBox(height: 12),
            FilledButton.icon(
              onPressed: _loading || _saving ? null : _add,
              icon: const Icon(Icons.add_rounded),
              label: const Text('노래 추가'),
            ),
            if (_error != null) ...[
              const SizedBox(height: 12),
              Text(
                _error!,
                style: TextStyle(color: Theme.of(context).colorScheme.error),
              ),
              TextButton(
                onPressed: _loading || _saving ? null : _load,
                child: const Text('목록 다시 불러오기'),
              ),
            ],
            const SizedBox(height: 24),
            Text(
              '등록된 노래 ${_songs.length}/30',
              style: Theme.of(context).textTheme.titleMedium,
            ),
            const SizedBox(height: 10),
            if (_loading) const Center(child: CircularProgressIndicator()),
            if (!_loading && _songs.isEmpty) const Text('아직 등록된 노래가 없습니다.'),
            for (final song in _songs)
              Card(
                child: ListTile(
                  leading: const Icon(Icons.music_note_rounded),
                  title: Text(song.title),
                  subtitle: Text(
                    song.url,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  trailing: IconButton(
                    tooltip: '${song.title} 삭제',
                    icon: const Icon(Icons.delete_outline_rounded),
                    onPressed: _saving
                        ? null
                        : () => _save(
                            _songs
                                .where((item) => item.videoId != song.videoId)
                                .toList(),
                          ),
                  ),
                ),
              ),
          ],
        ),
      ),
    );
  }
}
