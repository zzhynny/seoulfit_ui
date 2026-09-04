import 'package:flutter/material.dart';
import 'package:go_router/go_router.dart';
import 'package:provider/provider.dart';

import '../data/repositories/events_repository.dart';
import '../data/repositories/lens_repository.dart';
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

  // Auto-advancing loaders only — standalone, no bottom nav, since they're
  // brief full-screen transitions rather than places to switch tabs from.
  static const craftingItinerary = '/crafting-itinerary';
  static const reoptimizing = '/reoptimizing';

  static const error = '/error';

  static const chat = '/chat';
  static const trip = '/trip';
  static const lens = '/lens';
  static const events = '/events';
  static const profile = '/profile';

  // Nested under the Trip tab (see below) so the bottom nav stays visible.
  static const confirmSlots = '$trip/confirm-slots';
  static const initialItinerary = '$trip/initial-itinerary';
  static const makeTripYours = '$trip/make-trip-yours';
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
        builder: (context, state) {
          // Reused for two entry points: the linear onboarding flow, and
          // Profile's "Change" link (?from=profile) — both push() here, so
          // onBack always just pops back to whichever screen opened it.
          // Only onContinue's destination differs.
          final fromProfile = state.uri.queryParameters['from'] == 'profile';
          return ChooseBuddyScreen(
            showProgress: !fromProfile,
            onContinue: fromProfile ? () => context.pop() : () => context.push(AppRoutes.permissions),
            onBack: () => context.pop(),
          );
        },
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

      // Auto-advancing loaders — standalone, full-screen, no bottom nav (no
      // back arrow of their own either). Pushed as a top-level route over
      // the whole shell, then `go()` back into a nested Trip-tab screen when
      // done, so the shell's bottom nav is showing again immediately.
      GoRoute(
        path: AppRoutes.craftingItinerary,
        builder: (context, state) => CraftingItineraryScreen(
          onDone: () async {
            await context.read<TripProvider>().generateItinerary();
            if (context.mounted) context.go(AppRoutes.initialItinerary);
          },
        ),
      ),
      GoRoute(
        path: AppRoutes.reoptimizing,
        builder: (context, state) => ReoptimizingScreen(
          onDone: () async {
            await context.read<TripProvider>().reoptimize();
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
                // Cross-branch jump into the Trip tab's wizard — go(), not
                // push(), since Confirm Slots now lives inside the Trip
                // branch's own nested Navigator, not this one.
                onBuildItinerary: () => context.go(AppRoutes.confirmSlots),
              ),
            ),
          ]),
          StatefulShellBranch(routes: [
            GoRoute(
              path: AppRoutes.trip,
              builder: (context, state) => TripBranchRoot(
                onStartPlanning: () => context.go(AppRoutes.chat),
                onEditTrip: () => context.go(AppRoutes.makeTripYours),
                onCheckInToday: () {
                  final trip = context.read<TripProvider>();
                  // Priority order: a fully-completed trip always jumps to
                  // the recap; otherwise the one-time stamp opt-in gates
                  // the first tap, and every tap after that goes straight
                  // to today's check-in.
                  if (trip.isTripCompleted) {
                    context.go('${AppRoutes.profile}/recap');
                  } else if (!trip.hasRespondedToStampOptIn) {
                    context.push('${AppRoutes.trip}/stamp-book-optin');
                  } else {
                    context.push('${AppRoutes.trip}/day-checkin/1');
                  }
                },
              ),
              routes: [
                GoRoute(
                  path: 'confirm-slots',
                  builder: (context, state) {
                    final trip = context.read<TripProvider>();
                    final preferences = trip.itinerary?.preferences ?? _kDefaultPreferences;
                    return ConfirmSlotsScreen(
                      preferences: preferences,
                      onGenerate: () => context.push(AppRoutes.craftingItinerary),
                      onBack: () => context.go(AppRoutes.chat),
                    );
                  },
                ),
                GoRoute(
                  path: 'initial-itinerary',
                  builder: (context, state) {
                    final itinerary = context.watch<TripProvider>().itinerary;
                    if (itinerary == null) {
                      return const Center(child: CircularProgressIndicator());
                    }
                    return InitialItineraryScreen(
                      itinerary: itinerary,
                      onStartExploring: () => context.push('${AppRoutes.trip}/make-trip-yours'),
                      // The Crafting loader replaced itself via go(), so
                      // there's no stack entry to pop back to — go directly
                      // to Confirm Slots, the real prior decision point.
                      onBack: () => context.go(AppRoutes.confirmSlots),
                    );
                  },
                ),
                GoRoute(
                  path: 'make-trip-yours',
                  builder: (context, state) => MakeTripYoursScreen(
                    onOptimize: () => context.push(AppRoutes.reoptimizing),
                    onBack: () => context.pop(),
                  ),
                ),
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
                    // isTripCompleted is set on the Recap screen's own
                    // "Done" button, not here — merely viewing the recap
                    // shouldn't count as finishing the trip.
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
                // Top-level route (shared with onboarding), not nested under
                // /profile — a plain push()/pop() pair that can never
                // collide with whatever's on the Profile branch's own
                // nested stack (e.g. a still-open Recap route).
                onChangeCompanion: () => context.push('${AppRoutes.chooseBuddy}?from=profile'),
                onViewStampBook: () => context.push('${AppRoutes.profile}/recap?from=profile'),
              ),
              routes: [
                GoRoute(
                  path: 'recap',
                  builder: (context, state) {
                    // Two distinct entry points share this one route:
                    // Profile's "View Stamp Book & Recaps" (?from=profile,
                    // pushed within this same branch) vs. the check-in
                    // flow's Trip-Finish-Confirm "See My Trip Recap"
                    // (cross-branch go(), no query param). Done/back must
                    // behave differently for each.
                    final fromProfile = state.uri.queryParameters['from'] == 'profile';
                    return TripRecapScreen(
                      onDone: () {
                        if (fromProfile) {
                          // Just close back to Profile — the trip isn't
                          // necessarily finished, the user was only
                          // Browse-ing their stamp book.
                          context.pop();
                          return;
                        }
                        context.read<TripProvider>().markTripCompleted();
                        // Defensively unwind this branch's own stack back to
                        // its Profile root (so a later Profile-tab visit
                        // shows 12-5_Profile, not this Recap screen), then
                        // land on bare '/trip' — Final Route, not any stale
                        // nested check-in-wizard screen left over from before
                        // the cross-branch jump into this Recap screen.
                        while (context.canPop()) {
                          context.pop();
                        }
                        context.go(AppRoutes.trip);
                      },
                      onBack: () => context.pop(),
                    );
                  },
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
