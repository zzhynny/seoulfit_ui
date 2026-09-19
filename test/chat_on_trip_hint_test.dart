import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/data/mock/mock_trip_repository.dart';
import 'package:seoulfit_ui/data/repositories/chat_repository.dart';
import 'package:seoulfit_ui/models/chat.dart';
import 'package:seoulfit_ui/models/trip.dart';
import 'package:seoulfit_ui/providers/companion_provider.dart';
import 'package:seoulfit_ui/providers/trip_provider.dart';
import 'package:seoulfit_ui/screens/chat/chat_screen.dart';

class _Repo implements ChatRepository {
  @override
  Future<List<ChatMessage>> fetchConversation() async => const [
        ChatMessage(sender: ChatSender.bot, text: 'Your plan is ready.'),
      ];

  @override
  Future<ChatMessage> sendMessage(String text) async =>
      const ChatMessage(sender: ChatSender.bot, text: 'ok');

  @override
  List<OnTripHelpTopic> onTripTopics() => kOnTripTopics;
}

/// [narrow] mounts at 360px, the narrowest phone the header has to fit. Only
/// the header test uses it: test fonts draw every glyph a full em wide, so
/// unrelated rows overflow there that fit on a real device.
Future<List<LiveHelpTopic>> pumpChat(WidgetTester tester,
    {required bool hasPlan, bool narrow = false}) async {
  if (narrow) {
    tester.view.physicalSize = const Size(360, 780);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);
  }

  final repo = MockTripRepository();
  if (hasPlan) {
    repo.seedItinerary = Itinerary(
      preferences: const TripPreferences(
        dateRange: '', region: '', travelStyle: '',
        groupSize: '', dietaryNotes: '', pace: '',
      ),
      days: const [],
      routeStops: const [],
    );
  }
  final trip = TripProvider(repo);
  final opened = <LiveHelpTopic>[];

  await tester.pumpWidget(MultiProvider(
    providers: [
      Provider<ChatRepository>.value(value: _Repo()),
      ChangeNotifierProvider(create: (_) => CompanionProvider()),
      ChangeNotifierProvider.value(value: trip),
    ],
    child: MaterialApp(
      home: Scaffold(
        body: ChatScreen(
          onOpenHelpTopic: opened.add,
          onBuildItinerary: () {},
          onOpenDayPlanner: () {},
        ),
      ),
    ),
  ));
  // Not awaited: the mock repository's 200ms delay runs on the test's fake
  // clock, which only moves when pumped -- awaiting it here never returns.
  trip.loadCurrentTrip();
  await tester.pump(const Duration(milliseconds: 300));
  await tester.pumpAndSettle();
  return opened;
}

void main() {
  testWidgets('no plan yet: no on-trip card, and the header still fits',
      (tester) async {
    await pumpChat(tester, hasPlan: false, narrow: true);

    expect(find.textContaining('In Seoul now?'), findsNothing);
    expect(find.text('On-trip'), findsOneWidget);
    expect(tester.takeException(), isNull);
  });

  testWidgets('with a plan, the card opens a topic directly', (tester) async {
    // Testers never found the header toggle. Once there's a plan, the three
    // topics people need in a hurry sit right in the Plan chat.
    final opened = await pumpChat(tester, hasPlan: true);

    expect(find.textContaining('In Seoul now?'), findsOneWidget);
    await tester.tap(find.text('🏥 Emergency Room'));
    expect(opened, [LiveHelpTopic.emergency]);
  });

  testWidgets('"All on-trip help" switches the mode', (tester) async {
    await pumpChat(tester, hasPlan: true);

    await tester.tap(find.text('All on-trip help →'));
    await tester.pumpAndSettle();

    expect(find.text('How can we help?'), findsOneWidget);
  });

  testWidgets('the card can be dismissed', (tester) async {
    await pumpChat(tester, hasPlan: true);

    await tester.tap(find.byTooltip('Hide'));
    await tester.pumpAndSettle();

    expect(find.textContaining('In Seoul now?'), findsNothing);
  });
}
