part of '../guardian_home_page.dart';

class _AnomalyMetric extends StatelessWidget {
  const _AnomalyMetric({required this.label, required this.value});

  final String label;
  final String value;

  @override
  Widget build(BuildContext context) {
    return Column(
      children: [
        Text(
          label,
          style: const TextStyle(color: Color(0xFF806F5D), fontSize: 11),
        ),
        const SizedBox(height: 3),
        Text(
          value,
          style: const TextStyle(
            color: Color(0xFF744618),
            fontSize: 16,
            fontWeight: FontWeight.w900,
          ),
        ),
      ],
    );
  }
}

class _TabFrame extends StatelessWidget {
  const _TabFrame({
    required this.title,
    required this.subtitle,
    required this.children,
  });

  final String title;
  final String subtitle;
  final List<Widget> children;

  @override
  Widget build(BuildContext context) {
    return SafeArea(
      child: Center(
        child: ConstrainedBox(
          constraints: const BoxConstraints(maxWidth: 620),
          child: ListView(
            padding: const EdgeInsets.fromLTRB(20, 24, 20, 32),
            children: [
              Text(
                title,
                style: TextStyle(
                  color: _primaryText(context),
                  fontSize: 26,
                  fontWeight: FontWeight.w900,
                  letterSpacing: -0.7,
                ),
              ),
              const SizedBox(height: 5),
              Text(
                subtitle,
                style: TextStyle(color: _secondaryText(context), fontSize: 14),
              ),
              const SizedBox(height: 24),
              ...children,
            ],
          ),
        ),
      ),
    );
  }
}

class _DoorEventImage extends StatefulWidget {
  const _DoorEventImage({
    required this.imageUrl,
    required this.semanticLabel,
    required this.loadBytes,
    this.naturalHeight = false,
  });

  final String imageUrl;
  final String semanticLabel;
  final Future<Uint8List> Function() loadBytes;
  final bool naturalHeight;

  @override
  State<_DoorEventImage> createState() => _DoorEventImageState();
}

class _DoorEventImageState extends State<_DoorEventImage> {
  Future<Uint8List>? _photo;

  @override
  void initState() {
    super.initState();
    _loadPhoto();
  }

  @override
  void didUpdateWidget(covariant _DoorEventImage oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.imageUrl != widget.imageUrl) _loadPhoto();
  }

  void _loadPhoto() {
    _photo = widget.imageUrl.startsWith('asset://') ? null : widget.loadBytes();
  }

  @override
  Widget build(BuildContext context) {
    final Widget image;
    if (widget.imageUrl.startsWith('asset://')) {
      image = Image.asset(
        widget.imageUrl.substring('asset://'.length),
        fit: BoxFit.contain,
        width: double.infinity,
        height: widget.naturalHeight ? null : double.infinity,
        errorBuilder: _buildError,
      );
    } else {
      image = FutureBuilder<Uint8List>(
        future: _photo,
        builder: (context, snapshot) {
          if (snapshot.hasError) {
            return _buildError(context, snapshot.error!, null);
          }
          final bytes = snapshot.data;
          if (bytes != null) {
            return Image.memory(
              bytes,
              fit: BoxFit.contain,
              width: double.infinity,
              height: widget.naturalHeight ? null : double.infinity,
              errorBuilder: _buildError,
            );
          }
          return SizedBox(
            height: widget.naturalHeight ? 180 : null,
            child: const ColoredBox(
              color: Color(0xFFE8EFEC),
              child: Center(child: CircularProgressIndicator()),
            ),
          );
        },
      );
    }

    return Semantics(image: true, label: widget.semanticLabel, child: image);
  }

  Widget _buildError(
    BuildContext context,
    Object error,
    StackTrace? stackTrace,
  ) {
    return ColoredBox(
      color: const Color(0xFFE8EFEC),
      child: Center(
        child: TextButton(
          onPressed: () => setState(_loadPhoto),
          child: const Text('사진 재시도'),
        ),
      ),
    );
  }
}

class _DoorEventRecordCard extends StatelessWidget {
  const _DoorEventRecordCard({
    required this.event,
    required this.loadBytes,
    required this.confirmed,
    required this.onTap,
  });

  final DoorEvent event;
  final Future<Uint8List> Function() loadBytes;
  final bool confirmed;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Semantics(
      button: true,
      label: '${event.directionLabel} 출입 기록 상세보기',
      child: Card(
        clipBehavior: Clip.antiAlias,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
        child: InkWell(
          onTap: onTap,
          child: Row(
            children: [
              SizedBox(
                width: 122,
                height: 96,
                child: _DoorEventImage(
                  imageUrl: event.imageUrl,
                  loadBytes: loadBytes,
                  semanticLabel: '${event.directionLabel} 당시 현관 장면',
                ),
              ),
              Expanded(
                child: Padding(
                  padding: const EdgeInsets.all(13),
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Row(
                        children: [
                          Text(
                            event.directionLabel,
                            style: const TextStyle(
                              color: _green,
                              fontSize: 12,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                          const Spacer(),
                          if (confirmed)
                            const Icon(
                              Icons.verified_rounded,
                              color: _green,
                              size: 17,
                            ),
                        ],
                      ),
                      const SizedBox(height: 5),
                      Text(
                        event.title,
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                        style: TextStyle(
                          color: _primaryText(context),
                          fontWeight: FontWeight.w800,
                        ),
                      ),
                      const SizedBox(height: 5),
                      Text(
                        event.timeLabel,
                        style: TextStyle(
                          color: _secondaryText(context),
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              Padding(
                padding: const EdgeInsets.only(right: 10),
                child: Icon(
                  Icons.chevron_right_rounded,
                  color: _secondaryText(context),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _NotificationCard extends StatelessWidget {
  const _NotificationCard({
    required this.alert,
    this.acknowledged = false,
    this.pausedDuration,
    this.onConfirmNormal,
    this.onResume,
    required this.onTap,
  });

  final GuardianAlert alert;
  final bool acknowledged;
  final String? pausedDuration;
  final VoidCallback? onConfirmNormal;
  final VoidCallback? onResume;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: InkWell(
        borderRadius: BorderRadius.circular(20),
        onTap: onTap,
        child: Padding(
          padding: const EdgeInsets.all(16),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 46,
                height: 46,
                decoration: BoxDecoration(
                  color: _alertBackground(alert.type),
                  borderRadius: BorderRadius.circular(14),
                ),
                child: Icon(
                  _alertIcon(alert.type),
                  color: _alertColor(alert.type),
                ),
              ),
              const SizedBox(width: 13),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      children: [
                        Expanded(
                          child: Text(
                            alert.title,
                            style: TextStyle(
                              color: _primaryText(context),
                              fontSize: 15,
                              fontWeight: FontWeight.w800,
                            ),
                          ),
                        ),
                        Text(
                          acknowledged
                              ? '알림 중지 중'
                              : alert.isServerAlert && !alert.isRead
                              ? '미확인'
                              : alert.category,
                          style: TextStyle(
                            color: acknowledged
                                ? const Color(0xFF356B5A)
                                : _alertColor(alert.type),
                            fontSize: 11,
                            fontWeight: FontWeight.w700,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      acknowledged
                          ? '$pausedDuration 반복행동 알림을 보내지 않아요. 기록은 유지됩니다.'
                          : alert.description,
                      style: TextStyle(
                        color: _secondaryText(context),
                        fontSize: 13,
                      ),
                    ),
                    const SizedBox(height: 9),
                    Text(
                      alert.timeLabel,
                      style: TextStyle(
                        color: _secondaryText(context),
                        fontSize: 11,
                      ),
                    ),
                    if (onConfirmNormal != null) ...[
                      const SizedBox(height: 10),
                      SizedBox(
                        width: double.infinity,
                        child: acknowledged
                            ? OutlinedButton.icon(
                                onPressed: onResume,
                                icon: const Icon(
                                  Icons.notifications_active_outlined,
                                  size: 18,
                                ),
                                label: const Text('알림 다시 켜기'),
                              )
                            : FilledButton.tonalIcon(
                                onPressed: onConfirmNormal,
                                icon: const Icon(
                                  Icons.check_circle_outline_rounded,
                                  size: 18,
                                ),
                                label: const Text('정상으로 확인'),
                              ),
                      ),
                    ],
                  ],
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _TimelineTile extends StatelessWidget {
  const _TimelineTile({
    required this.time,
    required this.title,
    required this.icon,
    required this.onTap,
  });

  final String time;
  final String title;
  final IconData icon;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return ListTile(
      onTap: onTap,
      contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 5),
      leading: CircleAvatar(
        backgroundColor: const Color(0xFFE5F1EC),
        foregroundColor: const Color(0xFF356B5A),
        child: Icon(icon, size: 20),
      ),
      title: Text(title, style: const TextStyle(fontWeight: FontWeight.w700)),
      subtitle: Text(time),
    );
  }
}

class _PatientMetric extends StatelessWidget {
  const _PatientMetric({
    required this.label,
    required this.value,
    required this.icon,
  });

  final String label;
  final String value;
  final IconData icon;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisAlignment: MainAxisAlignment.center,
      children: [
        Icon(icon, color: const Color(0xFFDCEBE5), size: 19),
        const SizedBox(width: 8),
        Flexible(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                label,
                style: const TextStyle(color: Color(0xFFC9DDD6), fontSize: 11),
              ),
              const SizedBox(height: 2),
              Text(
                value,
                overflow: TextOverflow.ellipsis,
                style: const TextStyle(
                  color: Colors.white,
                  fontSize: 13,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

class _StatusCard extends StatelessWidget {
  const _StatusCard({
    required this.icon,
    required this.iconColor,
    required this.iconBackground,
    required this.label,
    required this.value,
    required this.detail,
  });

  final IconData icon;
  final Color iconColor;
  final Color iconBackground;
  final String label;
  final String value;
  final String detail;

  @override
  Widget build(BuildContext context) {
    return Card(
      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(20)),
      child: Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Container(
              width: 40,
              height: 40,
              decoration: BoxDecoration(
                color: iconBackground,
                borderRadius: BorderRadius.circular(12),
              ),
              child: Icon(icon, color: iconColor, size: 22),
            ),
            const SizedBox(height: 16),
            Text(
              label,
              style: TextStyle(color: _secondaryText(context), fontSize: 12),
            ),
            const SizedBox(height: 3),
            Text(
              value,
              style: TextStyle(
                color: _primaryText(context),
                fontSize: 20,
                fontWeight: FontWeight.w800,
              ),
            ),
            const SizedBox(height: 3),
            Text(
              detail,
              style: TextStyle(color: _secondaryText(context), fontSize: 11),
            ),
          ],
        ),
      ),
    );
  }
}

class _AlertTile extends StatelessWidget {
  const _AlertTile({
    required this.icon,
    required this.iconColor,
    required this.iconBackground,
    required this.title,
    required this.subtitle,
    required this.onTap,
  });

  final IconData icon;
  final Color iconColor;
  final Color iconBackground;
  final String title;
  final String subtitle;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(
          children: [
            Container(
              width: 42,
              height: 42,
              decoration: BoxDecoration(
                color: iconBackground,
                borderRadius: BorderRadius.circular(13),
              ),
              child: Icon(icon, color: iconColor, size: 22),
            ),
            const SizedBox(width: 13),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: TextStyle(
                      color: _primaryText(context),
                      fontSize: 14,
                      fontWeight: FontWeight.w700,
                    ),
                  ),
                  const SizedBox(height: 4),
                  Text(
                    subtitle,
                    style: TextStyle(
                      color: _secondaryText(context),
                      fontSize: 11,
                    ),
                  ),
                ],
              ),
            ),
            Icon(Icons.chevron_right_rounded, color: _secondaryText(context)),
          ],
        ),
      ),
    );
  }
}

class _QuickAction extends StatelessWidget {
  const _QuickAction({
    required this.icon,
    required this.label,
    required this.onTap,
  });

  final IconData icon;
  final String label;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Material(
      color: _surfaceColor(context),
      borderRadius: BorderRadius.circular(16),
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(16),
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 15),
          child: Column(
            children: [
              Icon(icon, color: const Color(0xFF356B5A), size: 25),
              const SizedBox(height: 8),
              Text(
                label,
                textAlign: TextAlign.center,
                style: TextStyle(
                  color: _primaryText(context),
                  fontSize: 12,
                  fontWeight: FontWeight.w700,
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
