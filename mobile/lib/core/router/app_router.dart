import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:go_router/go_router.dart';

import '../../features/auth/presentation/login_screen.dart';
import '../../features/home/home_screen.dart';
import '../../features/moodle/domain/course.dart';
import '../../features/moodle/presentation/connect_moodle_screen.dart';
import '../../features/moodle/presentation/courses_screen.dart';
import '../../features/quiz/presentation/approval_screen.dart';
import '../../features/quiz/presentation/generate_quiz_screen.dart';
import '../../features/quiz/presentation/publish_status_screen.dart';
import '../../features/quiz/presentation/quiz_preview_screen.dart';
import '../providers.dart';

final appRouterProvider = Provider<GoRouter>((ref) {
  final session = ref.watch(sessionProvider);

  return GoRouter(
    initialLocation: session == null ? '/login' : '/home',
    redirect: (context, state) {
      final loggedIn = ref.read(sessionProvider) != null;
      final loggingIn = state.matchedLocation == '/login';
      if (!loggedIn && !loggingIn) return '/login';
      if (loggedIn && loggingIn) return '/home';
      return null;
    },
    routes: [
      GoRoute(path: '/login', builder: (_, __) => const LoginScreen()),
      GoRoute(path: '/home', builder: (_, __) => const HomeScreen()),
      GoRoute(path: '/moodle/connect', builder: (_, __) => const ConnectMoodleScreen()),
      GoRoute(path: '/courses', builder: (_, __) => const CoursesScreen()),
      GoRoute(
        path: '/courses/:courseId/generate',
        builder: (context, state) {
          final extra = state.extra;
          final course = extra is CourseSummary
              ? extra
              : CourseSummary(
                  id: state.pathParameters['courseId'] ?? '',
                  title: 'مقرر',
                );
          return GenerateQuizScreen(course: course);
        },
      ),
      GoRoute(
        path: '/tasks/:taskId/preview',
        builder: (_, state) => QuizPreviewScreen(
          taskId: state.pathParameters['taskId'] ?? '',
        ),
      ),
      GoRoute(
        path: '/tasks/:taskId/approval',
        builder: (_, state) => ApprovalScreen(
          taskId: state.pathParameters['taskId'] ?? '',
        ),
      ),
      GoRoute(
        path: '/tasks/:taskId/publish',
        builder: (_, state) => PublishStatusScreen(
          taskId: state.pathParameters['taskId'] ?? '',
        ),
      ),
    ],
  );
});
