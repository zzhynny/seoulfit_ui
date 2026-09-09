import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/data/repositories/chat_repository.dart';
import 'package:seoulfit_ui/models/chat.dart';
import 'package:seoulfit_ui/providers/companion_provider.dart';
import 'package:seoulfit_ui/screens/chat/chat_screen.dart';

/// Starts on the confirm summary (readyToBuild) and, on the next sent
/// message, bounces back to day_plan -- the same shape as a confirm-stage
/// `travel_dates` edit that changes trip length (backend/graph.py `_ask`,
/// which recomputes `day_specs` and sets `current_step` back to
/// `day_plan`). Regression test for the dead "Build My Itinerary" button:
/// with a stale `.any(readyToBuild)` check, both CTAs render after the
/// bounce and tapping Build reaches a step that produces no itinerary.
class _BouncingRepository implements ChatRepository {
  static const _confirmMessage = ChatMessage(
    sender: ChatSender.bot,
    text: 'Here is your plan summary.',
    awaitingStep: 'confirm',
    readyToBuild: true,
  );

  static const _dayPlanMessage = ChatMessage(
    sender: ChatSender.bot,
    text: 'Got it. Now pick an area and a focus for each day.',
    awaitingStep: 'day_plan',
    readyToBuild: false,
  );

  @override
  Future<List<ChatMessage>> fetchConversation() async => [_confirmMessage];

  @override
  Future<ChatMessage> sendMessage(String text) async => _dayPlanMessage;

  @override
  List<OnTripHelpTopic> onTripTopics() => kOnTripTopics;
}

Future<void> pumpChat(WidgetTester tester, ChatRepository repository) async {
  await tester.pumpWidget(MultiProvider(
    providers: [
      Provider<ChatRepository>.value(value: repository),
      ChangeNotifierProvider(create: (_) => CompanionProvider()),
    ],
    child: MaterialApp(
      home: Scaffold(
        body: ChatScreen(
          onOpenHelpTopic: (_) {},
          onBuildItinerary: () {},
          onOpenDayPlanner: () {},
        ),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets(
      'Build My Itinerary disappears once the thread bounces back to day_plan',
      (tester) async {
    await pumpChat(tester, _BouncingRepository());

    // Confirm stage: only the Build CTA shows.
    expect(find.text('Ready? Build My Itinerary →'), findsOneWidget);
    expect(find.text('Plan each day'), findsNothing);

    // Send a turn (e.g. "change dates" to a different trip length) -- the
    // fake backend answers with a day_plan-step message, same as the real
    // backend's `_ask` fallback when day_specs no longer matches the trip.
    await tester.enterText(find.byType(TextField), 'change dates to 2 days');
    await tester.tap(find.byIcon(Icons.send));
    await tester.pumpAndSettle();

    // Only the day_plan CTA should show now -- the stale confirm-summary
    // message's readyToBuild must not resurrect the Build button.
    expect(find.text('Plan each day'), findsOneWidget);
    expect(find.text('Ready? Build My Itinerary →'), findsNothing);
  });
}
