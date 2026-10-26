class FavoriteSong {
  const FavoriteSong({
    required this.videoId,
    required this.title,
    required this.url,
  });

  final String videoId;
  final String title;
  final String url;

  factory FavoriteSong.fromJson(Map<String, dynamic> json) => FavoriteSong(
    videoId: json['video_id'] as String,
    title: json['title'] as String,
    url: json['url'] as String,
  );

  Map<String, String> toRequestJson() => {'title': title, 'url': url};
}
