import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../features/auth/data/auth_repository.dart';
import '../features/auth/domain/session.dart';
import '../features/moodle/data/moodle_repository.dart';
import '../features/quiz/data/quiz_repository.dart';
import 'api/api_client.dart';
import 'app_config.dart';

final appConfigProvider = Provider<AppConfig>(
  (ref) => throw UnimplementedError('appConfigProvider must be overridden'),
);

final apiClientProvider = Provider<ApiClient>((ref) {
  final config = ref.watch(appConfigProvider);
  return ApiClient(config: config);
});

final sessionProvider = StateProvider<TeacherSession?>((ref) => null);

final authRepositoryProvider = Provider<AuthRepository>((ref) {
  final config = ref.watch(appConfigProvider);
  if (config.useMocks) return MockAuthRepository();
  return ApiAuthRepository(ref.watch(apiClientProvider), SecureTokenStore());
});

final moodleRepositoryProvider = Provider<MoodleRepository>((ref) {
  final config = ref.watch(appConfigProvider);
  if (config.useMocks) return MockMoodleRepository();
  return ApiMoodleRepository(ref.watch(apiClientProvider), connectionId: config.connectionId);
});

final quizRepositoryProvider = Provider<QuizRepository>((ref) {
  final config = ref.watch(appConfigProvider);
  if (config.useMocks) return MockQuizRepository();
  return ApiQuizRepository(ref.watch(apiClientProvider));
});
