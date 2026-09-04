import 'package:flutter/material.dart';
import 'package:provider/provider.dart';

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
import 'theme/theme.dart';
import 'widgets/figma_chrome.dart';

void main() {
  runApp(const SeoulFitApp());
}

class SeoulFitApp extends StatelessWidget {
  const SeoulFitApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        Provider<ChatRepository>(create: (_) => MockChatRepository()),
        Provider<TripRepository>(create: (_) => MockTripRepository()),
        Provider<LensRepository>(create: (_) => MockLensRepository()),
        Provider<EventsRepository>(create: (_) => MockEventsRepository()),
        Provider<ProfileRepository>(create: (_) => MockProfileRepository()),
        ChangeNotifierProvider(create: (_) => CompanionProvider()),
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
              return Stack(
                children: [
                  ?child,
                  const FigmaChromeToggleButton(),
                ],
              );
            },
          );
        },
      ),
    );
  }
}
