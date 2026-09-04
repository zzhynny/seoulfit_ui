import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../data/repositories/events_repository.dart';
import '../data/repositories/lens_repository.dart';
import '../data/repositories/profile_repository.dart';
import '../models/lens.dart';
import '../models/trip.dart';
import '../providers/trip_provider.dart';
import '../widgets/main_shell.dart';

import '../screens/onboarding/splash_screen.dart';
import '../screens/onboarding/enter_name_screen.dart';
import '../screens/onboarding/choose_buddy_screen.dart';
import '../screens/onboarding/permissions_screen.dart';

import '../screens/chat/chat_screen.dart';

import '../screens/trip/trip_branch_root.dart';
import '../screens/trip/confirm_slots_screen.dart';
import '../screens/trip/crafting_itinerary_screen.dart';
import '../screens/trip/initial_itinerary_screen.dart';
import '../screens/trip/make_trip_yours_screen.dart';
import '../screens/trip/reoptimizing_screen.dart';
import '../screens/trip/stamp_book_optin_screen.dart';
import '../screens/trip/day_checkin_screen.dart';
import '../screens/trip/missed_reason_screen.dart';
import '../screens/trip/day_complete_screen.dart';
import '../screens/trip/trip_finish_confirm_screen.dart';

import '../screens/lens/lens_scan_screen.dart';
import '../screens/lens/lens_result_screen.dart';

import '../screens/events/events_screen.dart';

import '../screens/profile/profile_screen.dart';
import '../screens/profile/trip_recap_screen.dart';

import '../screens/global/error_screen.dart';

/// SeoulFit route paths.
class AppRoutes {
  AppRoutes._();

  static const splash = '/splash';
  static const enterName = '/enter-name';
  static const chooseBuddy = '/choose-buddy';
  static const permissions = '/permissions';

  static const confirmSlots = '/confirm-slots';
  static const craftingItinerary = '/crafting-itinerary';
  static const initialItinerary = '/initial-itinerary';
  static const makeTripYours = '/make-trip-yours';
  static const reoptimizing = '/reoptimizing';

  static const error = '/error';

  static const chat = '/chat';
  static const trip = '/trip';
  static const lens = '/lens';
  static const events = '/events';
  static const profile = '/profile';
}

GoRouter buildAppRouter() {
  return GoRouter(
    initialLocation: AppRoutes.splash,
    routes: [
      GoRoute(
        path: AppRoutes.splash,
        builder: (context, state) => SplashScreen(
          onGetStarted: () => context.push(AppRoutes.enterName),
        ),
      ),
      GoRoute(
        path: AppRoutes.enterName,
        builder: (context, state) => EnterNameScreen(
          onContinue: () => context.push(AppRoutes.chooseBuddy),
          onBack: () => context.pop(),
        ),
      ),
      GoRoute(
        path: AppRoutes.chooseBuddy,
        builder: (context, state) => ChooseBuddyScreen(
          onContinue: () => context.push(AppRoutes.permissions),
          onBack: () => context.pop(),
        ),
      ),
      GoRoute(
        path: AppRoutes.permissions,
        builder: (context, state) => PermissionsScreen(
          // Terminal onboarding step: replace the whole onboarding stack
          // with the persistent tab shell (no back-into-onboarding from Chat).
          onContinue: () => context.go(AppRoutes.chat),
          onBack: () => context.pop(),
        ),
      ),

      // Trip wizard — standalone, full-screen, no bottom nav until Final Route.
      // Forward taps push (so each screen's back arrow can pop to its real
      // entry point); auto-advancing loaders pushReplacement themselves off
      // the stack since they have no back arrow of their own.
      GoRoute(
        path: AppRoutes.confirmSlots,
        builder: (context, state) {
          final trip = context.read<TripProvider>();
          final preferences = trip.itinerary?.preferences ?? _kDefaultPreferences;
          return ConfirmSlotsScreen(
            preferences: preferences,
            onGenerate: () => context.push(AppRoutes.craftingItinerary),
            onBack: () => context.pop(),
          );
        },
      ),
      GoRoute(
        path: AppRoutes.craftingItinerary,
        builder: (context, state) => CraftingItineraryScreen(
          onDone: () async {
            await context.read<TripProvider>().generateItinerary();
            if (context.mounted) context.pushReplacement(AppRoutes.initialItinerary);
          },
        ),
      ),
      GoRoute(
        path: AppRoutes.initialItinerary,
        builder: (context, state) {
          final itinerary = context.watch<TripProvider>().itinerary;
          if (itinerary == null) {
            return const Scaffold(body: Center(child: CircularProgressIndicator()));
          }
          return InitialItineraryScreen(
            itinerary: itinerary,
            onStartExploring: () => context.push(AppRoutes.makeTripYours),
            // Crafting was pushReplaced off the stack, so back lands on
            // Confirm Slots — the real prior decision point.
            onBack: () => context.pop(),
          );
        },
      ),
      GoRoute(
        path: AppRoutes.makeTripYours,
        builder: (context, state) => MakeTripYoursScreen(
          onOptimize: () => context.push(AppRoutes.reoptimizing),
          onBack: () => context.pop(),
        ),
      ),
      GoRoute(
        path: AppRoutes.reoptimizing,
        builder: (context, state) => ReoptimizingScreen(
          onDone: () async {
            await context.read<TripProvider>().reoptimize();
            // Terminal wizard step: replace the whole wizard stack with the
            // Trip tab (Final Route) — no back-into-wizard from there.
            if (context.mounted) context.go(AppRoutes.trip);
          },
        ),
      ),

      GoRoute(
        path: AppRoutes.error,
        builder: (context, state) => ErrorScreen(
          onTryAgain: () => context.pop(),
          onBackToHome: () => context.go(AppRoutes.chat),
          onBack: () => context.pop(),
        ),
      ),

      StatefulShellRoute.indexedStack(
        builder: (context, state, navigationShell) => MainShell(navigationShell: navigationShell),
        branches: [
          StatefulShellBranch(routes: [
            GoRoute(
              path: AppRoutes.chat,
              builder: (context, state) => ChatScreen(
                onOpenHelpTopic: (title) => _showHelpTopicSheet(context, title),
                onBuildItinerary: () => context.push(AppRoutes.confirmSlots),
              ),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: AppRoutes.trip,
              builder: (context, state) => TripBranchRoot(
                onStartPlanning: () => context.go(AppRoutes.chat),
                onCheckInToday: () {
                  // One-time opt-in: ask via 13_Stamp-Book-OptIn the first
                  // time, then skip straight to Day Check-in afterwards.
                  final answered = context.read<TripProvider>().hasRespondedToStampOptIn;
                  if (answered) {
                    context.push('${AppRoutes.trip}/day-checkin/1');
                  } else {
                    context.push('${AppRoutes.trip}/stamp-book-optin');
                  }
                },
              ),
              routes: [
                GoRoute(
                  path: 'stamp-book-optin',
                  builder: (context, state) => StampBookOptInScreen(
                    onStartCollecting: (enabled) {
                      context.read<TripProvider>().respondToStampOptIn(enabled);
                      context.pushReplacement('${AppRoutes.trip}/day-checkin/1');
                    },
                    onSkip: () {
                      context.read<TripProvider>().respondToStampOptIn(false);
                      context.pop();
                    },
                  ),
                ),
                GoRoute(
                  path: 'day-checkin/:day',
                  builder: (context, state) {
                    final day = int.parse(state.pathParameters['day']!);
                    return DayCheckInScreen(
                      dayNumber: day,
                      onComplete: () => context.push('${AppRoutes.trip}/day-complete/$day'),
                      onMissedPlace: (activityId) =>
                          context.push('${AppRoutes.trip}/missed-reason/$day/$activityId'),
                    );
                  },
                ),
                GoRoute(
                  path: 'missed-reason/:day/:activityId',
                  builder: (context, state) {
                    final day = int.parse(state.pathParameters['day']!);
                    final activityId = state.pathParameters['activityId']!;
                    return MissedReasonScreen(
                      dayNumber: day,
                      activityId: activityId,
                      onConfirm: () => context.pop(),
                      onBack: () => context.pop(),
                    );
                  },
                ),
                GoRoute(
                  path: 'day-complete/:day',
                  builder: (context, state) {
                    final day = int.parse(state.pathParameters['day']!);
                    return DayCompleteScreen(
                      dayNumber: day,
                      onContinue: () => context.push('${AppRoutes.trip}/trip-finish-confirm'),
                      onBack: () => context.pop(),
                    );
                  },
                ),
                GoRoute(
                  path: 'trip-finish-confirm',
                  builder: (context, state) => TripFinishConfirmScreen(
                    onSeeRecap: () => context.go('${AppRoutes.profile}/recap'),
                    onNotYet: () => context.go(AppRoutes.trip),
                    onBack: () => context.pop(),
                  ),
                ),
              ],
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: AppRoutes.lens,
              builder: (context, state) => LensScanScreen(
                onScan: (source) async {
                  final result = await context.read<LensRepository>().scanPlace();
                  if (context.mounted) {
                    context.push('${AppRoutes.lens}/result', extra: result);
                  }
                },
              ),
              routes: [
                GoRoute(
                  path: 'result',
                  builder: (context, state) => LensResultScreen(
                    result: state.extra as LensPlaceResult,
                    onScanAnother: () => context.pop(),
                  ),
                ),
              ],
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: AppRoutes.events,
              builder: (context, state) => EventsScreen(repository: context.read<EventsRepository>()),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: AppRoutes.profile,
              builder: (context, state) => ProfileScreen(
                onChangeCompanion: () => context.push('${AppRoutes.profile}/choose-buddy'),
                onViewStampBook: () => context.push('${AppRoutes.profile}/recap'),
              ),
              routes: [
                GoRoute(
                  path: 'recap',
                  builder: (context, state) => TripRecapScreen(
                    repository: context.read<ProfileRepository>(),
                    onDone: () {
                      // Pop this branch's own stack back to its Profile root
                      // first, so switching back to the Profile tab later
                      // (StatefulShellRoute restores each branch's last
                      // location) lands on 12-5_Profile, not this recap
                      // screen.
                      if (context.canPop()) context.pop();
                      context.go(AppRoutes.trip);
                    },
                    onBack: () => context.pop(),
                  ),
                ),
                GoRoute(
                  path: 'choose-buddy',
                  builder: (context, state) => ChooseBuddyScreen(
                    showProgress: false,
                    onContinue: () => context.pop(),
                    onBack: () => context.pop(),
                  ),
                ),
              ],
            ),
          ]),
        ],
      ),
    ],
  );
}

const _kDefaultPreferences = TripPreferences(
  dateRange: 'Oct 12 – Oct 16',
  duration: '5 Days (Autumn)',
  travelStyle: 'Culture, K-Pop',
  groupSize: '2 Adults',
  dietaryNotes: 'Vegan Options',
);

void _showHelpTopicSheet(BuildContext context, String title) {
  showModalBottomSheet(
    context: context,
    backgroundColor: Colors.transparent,
    builder: (context) => Container(
      padding: const EdgeInsets.all(24),
      decoration: const BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.only(topLeft: Radius.circular(24), topRight: Radius.circular(24)),
      ),
      child: SafeArea(
        top: false,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(title, style: const TextStyle(fontSize: 20, fontWeight: FontWeight.bold)),
            const SizedBox(height: 12),
            const Text('Instant concierge results would appear here in the full app.'),
          ],
        ),
      ),
    ),
  );
}
