import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

import 'data/api/api_chat_repository.dart';
import 'data/api/api_events_repository.dart';
import 'data/api/api_lens_repository.dart';
import 'data/api/api_profile_repository.dart';
import 'data/api/api_trip_repository.dart';
import 'data/mock/mock_chat_repository.dart';
import 'data/mock/mock_events_repository.dart';
import 'data/mock/mock_lens_repository.dart';
import 'data/mock/mock_profile_repository.dart';
import 'data/mock/mock_trip_repository.dart';
import 'data/repositories/chat_repository.dart';
import 'data/repositories/events_repository.dart';
import 'data/repositories/lens_repository.dart';
import 'data/repositories/profile_repository.dart';
import 'data/repositories/trip_repository.dart';
import 'providers/companion_provider.dart';
import 'providers/trip_provider.dart';
import 'routes/app_routes.dart';
import 'services/api_service.dart';
import 'theme/theme.dart';
import 'widgets/figma_chrome.dart';

/// Runs against the mock repositories instead of the FastAPI backend:
///
///   flutter run --dart-define=USE_MOCKS=true
///
/// Kept because the mocks carry the Figma-parity content the screens were
/// designed against, and because the UI has to stay demoable with no backend
/// and no network.
const kUseMocks = bool.fromEnvironment('USE_MOCKS');

void main() {
  runApp(const SeoulFitApp());
}

class SeoulFitApp extends StatelessWidget {
  const SeoulFitApp({super.key});

  @override
  Widget build(BuildContext context) {
    // One ApiService, so one thread_id: the itinerary is a side effect of the
    // chat conversation, so Chat and Trip must talk to the same LangGraph
    // thread. Separate instances would plan against an empty set of answers.
    final api = ApiService();

    return MultiProvider(
      providers: [
        // Nullable on purpose: mock builds provide null, and PoiPhoto reads
        // it as `ApiService?` so it simply doesn't fetch.
        Provider<ApiService?>.value(value: kUseMocks ? null : api),
        Provider<ChatRepository>(
          create: (_) =>
              kUseMocks ? MockChatRepository() : ApiChatRepository(api),
        ),
        Provider<TripRepository>(
          create: (_) =>
              kUseMocks ? MockTripRepository() : ApiTripRepository(api),
        ),
        Provider<LensRepository>(
          create: (_) =>
              kUseMocks ? MockLensRepository() : ApiLensRepository(),
        ),
        Provider<EventsRepository>(
          create: (_) =>
              kUseMocks ? MockEventsRepository() : ApiEventsRepository(api),
        ),
        ChangeNotifierProvider(create: (_) => CompanionProvider()),
        // Depends on CompanionProvider: the profile's name is the one entered
        // during onboarding, which lives there and can change afterwards.
        ProxyProvider<CompanionProvider, ProfileRepository>(
          update: (_, companion, _) => kUseMocks
              ? MockProfileRepository()
              : ApiProfileRepository(api, displayName: companion.userName),
        ),
        ChangeNotifierProvider(
          create: (context) => TripProvider(context.read<TripRepository>()),
        ),
      ],
      child: Builder(
        builder: (context) {
          final router = buildAppRouter();
          return MaterialApp.router(
            title: 'SeoulFit',
            debugShowCheckedModeBanner: false,
            theme: AppTheme.light,
            routerConfig: router,
            builder: (context, child) {
              return ColoredBox(
                // Neutral backdrop for the letterboxed area on wide desktop
                // viewports, so the constrained app column reads clearly.
                color: const Color(0xFFE5E1D8),
                child: Stack(
                  children: [
                    Center(
                      child: ConstrainedBox(
                        constraints: const BoxConstraints(maxWidth: 430),
                        child: child ?? const SizedBox.shrink(),
                      ),
                    ),
                    const FigmaChromeToggleButton(),
                  ],
                ),
              );
            },
          );
        },
      ),
    );
  }
}
