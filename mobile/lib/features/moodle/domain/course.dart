class CourseSummary {
  const CourseSummary({
    required this.id,
    required this.title,
    this.shortName,
    this.visible = true,
  });

  final String id;
  final String title;
  final String? shortName;
  final bool visible;

  factory CourseSummary.fromJson(Map<String, dynamic> json) {
    return CourseSummary(
      id: json['id']?.toString() ?? json['course_id']?.toString() ?? '',
      title: json['fullname']?.toString() ?? json['fullnamename']?.toString() ?? '',
      shortName: json['short_name']?.toString() ?? json['shortname']?.toString(),
      visible: json['visible'] != false,
    );
  }
}

class MoodleConnectionStatus {
  const MoodleConnectionStatus({
    required this.connected,
    this.siteUrl,
    this.connectionId,
  });

  final bool connected;
  final String? siteUrl;
  final String? connectionId;
}
