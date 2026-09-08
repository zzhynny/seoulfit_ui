import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/data/mock/mock_trip_repository.dart';
import 'package:seoulfit_ui/data/repositories/trip_repository.dart';
import 'package:seoulfit_ui/models/plan_check.dart';
import 'package:seoulfit_ui/models/trip.dart';
import 'package:seoulfit_ui/providers/trip_provider.dart';
import 'package:seoulfit_ui/screens/trip/trip_branch_root.dart';
import 'package:shared_preferences/shared_preferences.dart';

/// /state that errors the way ApiService does when the backend is down,
/// slow, or returns non-200.
class ThrowingTripRepository implements TripRepository {
  final _inner = MockTripRepository();

  @override
  Future<Itinerary?> fetchCurrentItinerary() async {
    throw Exception('Backend error 500: boom');
  }

  @override
  Future<TripPreferences> fetchDefaultPreferences() =>
      _inner.fetchDefaultPreferences();

  @override
  Future<Itinerary> generateItinerary(TripPreferences p) =>
      _inner.generateItinerary(p);

  @override
  Future<(Itinerary, ReoptimizeResult)> reoptimizeItinerary(
    Itinerary itinerary, {
    Map<String, String> swappedSlots = const {},
  }) =>
      _inner.reoptimizeItinerary(itinerary, swappedSlots: swappedSlots);

  @override
  Future<List<SwapCandidate>> fetchSwapCandidates({
    required int day,
    required int slotIndex,
    required String currentPoi,
    required String dayArea,
    String currentPoiType = '',
    List<String> excludedIds = const [],
  }) async =>
      const [];
}

void main() {
  setUp(() => SharedPreferences.setMockInitialValues({}));

  Future<void> pumpBranch(WidgetTester tester, TripProvider p) async {
    await tester.pumpWidget(
      ChangeNotifierProvider<TripProvider>.value(
        value: p,
        child: MaterialApp(
          home: Scaffold(
            body: TripBranchRoot(
              onStartPlanning: () {},
              onCheckInToday: () {},
              onEditTrip: () {},
            ),
          ),
        ),
      ),
    );
    await tester.pump(const Duration(seconds: 1));
  }

  testWidgets('Trip tab still shows Final Route when /state fails', (tester) async {
    // The uncaught throw used to leave loading==true forever, so the tab was
    // a permanent spinner and the check-in button never rendered.
    final p = TripProvider(ThrowingTripRepository());
    await tester.runAsync(() => p.generateItinerary());
    expect(p.hasItinerary, isTrue, reason: 'itinerary was just generated');

    await pumpBranch(tester, p);

    // What the traveller sees on the Trip tab after generating a plan.
    final spinner = find.byType(CircularProgressIndicator);
    final checkIn = find.text("Check in for today's places →");
    debugPrint('--- loading=${p.loading} hasItinerary=${p.hasItinerary} '
        'spinner=${spinner.evaluate().length} checkInButton=${checkIn.evaluate().length}');
    tester.takeException();

    expect(checkIn, findsOneWidget,
        reason: 'the only entry into the stamp / check-in / recap flow');
  });

  testWidgets('remounting the Trip tab keeps stamps already collected', (tester) async {
    final p = TripProvider(MockTripRepository());
    await tester.runAsync(() async {
      await p.generateItinerary();
      // Mock seeds visited flags; clear them so the count is unambiguous.
      for (final d in p.itinerary!.days) {
        for (final a in d.activities) {
          p.setVisited(a.id, false);
        }
      }
      p.setVisited(p.itinerary!.days.first.activities.first.id, true);
    });
    expect(p.itinerary!.stampedDays, 1);

    // Returning to the Trip tab remounts this widget.
    await pumpBranch(tester, p);
    await tester.runAsync(() => Future<void>.delayed(const Duration(milliseconds: 400)));
    await tester.pump();
    tester.takeException();

    debugPrint('--- after remount: stampedDays=${p.itinerary?.stampedDays}');
    expect(p.itinerary?.stampedDays, 1,
        reason: 'a tab switch must not erase collected stamps');
  });
}
