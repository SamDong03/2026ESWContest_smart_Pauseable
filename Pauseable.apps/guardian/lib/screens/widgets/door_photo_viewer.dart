part of '../guardian_home_page.dart';

class _DoorPhotoViewerPage extends StatefulWidget {
  const _DoorPhotoViewerPage({required this.event, required this.loadBytes});

  final DoorEvent event;
  final Future<Uint8List> Function() loadBytes;

  @override
  State<_DoorPhotoViewerPage> createState() => _DoorPhotoViewerPageState();
}

class _DoorPhotoViewerPageState extends State<_DoorPhotoViewerPage> {
  final _transformation = TransformationController();
  Offset _doubleTapPosition = Offset.zero;

  void _resetZoom() {
    _transformation.value = Matrix4.identity();
  }

  void _toggleZoom() {
    if (_transformation.value.getMaxScaleOnAxis() > 1.01) {
      _resetZoom();
    } else {
      _transformation.value = Matrix4.diagonal3Values(3, 3, 1)
        ..setTranslationRaw(
          -_doubleTapPosition.dx * 2,
          -_doubleTapPosition.dy * 2,
          0,
        );
    }
  }

  @override
  void dispose() {
    _transformation.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: Colors.black,
      appBar: AppBar(
        backgroundColor: Colors.black,
        foregroundColor: Colors.white,
        leading: IconButton(
          tooltip: '사진 닫기',
          icon: const Icon(Icons.close_rounded),
          onPressed: () => Navigator.pop(context),
        ),
        title: Text(
          '${widget.event.directionLabel} · ${widget.event.timeLabel}',
        ),
        actions: [
          IconButton(
            tooltip: '사진 전체 보기',
            icon: const Icon(Icons.fit_screen_rounded),
            onPressed: _resetZoom,
          ),
        ],
      ),
      body: SafeArea(
        child: Column(
          children: [
            Expanded(
              child: LayoutBuilder(
                builder: (context, constraints) => GestureDetector(
                  onDoubleTapDown: (details) {
                    _doubleTapPosition = details.localPosition;
                  },
                  onDoubleTap: _toggleZoom,
                  child: InteractiveViewer(
                    transformationController: _transformation,
                    minScale: 1,
                    maxScale: 6,
                    child: SizedBox(
                      width: constraints.maxWidth,
                      height: constraints.maxHeight,
                      child: _DoorEventImage(
                        imageUrl: widget.event.imageUrl,
                        loadBytes: widget.loadBytes,
                        semanticLabel:
                            '${widget.event.directionLabel} 당시 현관 사진',
                      ),
                    ),
                  ),
                ),
              ),
            ),
            const Padding(
              padding: EdgeInsets.all(12),
              child: Text(
                '두 손가락으로 확대 · 두 번 눌러 확대',
                style: TextStyle(color: Colors.white70, fontSize: 13),
              ),
            ),
          ],
        ),
      ),
    );
  }
}
