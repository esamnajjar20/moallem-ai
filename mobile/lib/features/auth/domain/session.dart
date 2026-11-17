class TeacherSession {
  const TeacherSession({
    required this.userId,
    required this.displayName,
    required this.accessToken,
    required this.membershipId,
    required this.tenantId,
    this.moodleConnected = false,
  });

  final String userId;
  final String displayName;
  final String accessToken;
  final String membershipId;
  final String tenantId;
  final bool moodleConnected;

  TeacherSession copyWith({
    String? displayName,
    String? accessToken,
    bool? moodleConnected,
  }) {
    return TeacherSession(
      userId: userId,
      displayName: displayName ?? this.displayName,
      accessToken: accessToken ?? this.accessToken,
      membershipId: membershipId,
      tenantId: tenantId,
      moodleConnected: moodleConnected ?? this.moodleConnected,
    );
  }
}
