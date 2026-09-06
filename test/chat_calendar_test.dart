import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:seoulfit_ui/data/repositories/chat_repository.dart';
import 'package:seoulfit_ui/models/chat.dart';
import 'package:seoulfit_ui/providers/companion_provider.dart';
import 'package:seoulfit_ui/screens/chat/chat_screen.dart';

/// Returns one bot message asking about [field], the way ApiChatRepository
/// builds it from the backend's current_field.
class _AskingRepository implements ChatRepository {
  _AskingRepository(this.field, {this.quickReplies = const []});

  final String? field;
  final List<String> quickReplies;

  ChatMessage get _message => ChatMessage(
        sender: ChatSender.bot,
        text: 'question about $field',
        awaitingField: field,
        quickReplies: quickReplies,
      );

  @override
  Future<List<ChatMessage>> fetchConversation() async => [_message];

  @override
  Future<ChatMessage> sendMessage(String text) async => _message;

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
      // ChatScreen is a Column that normally lives inside MainShell's
      // Scaffold; its composer TextField needs that Material ancestor.
      home: Scaffold(
        body: ChatScreen(onOpenHelpTopic: (_) {}, onBuildItinerary: () {}),
      ),
    ),
  ));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('the calendar appears while the buddy waits on travel_dates',
      (tester) async {
    // The backend's dates question says "Tap the calendar" and rejects typed
    // answers, so this affordance is the only way to answer that slot.
    await pumpChat(tester, _AskingRepository('travel_dates'));

    expect(find.text('Pick your dates'), findsOneWidget);
    expect(find.byIcon(Icons.calendar_month_rounded), findsOneWidget);
  });

  testWidgets('and only for that slot', (tester) async {
    await pumpChat(
      tester,
      _AskingRepository('category', quickReplies: const ['Food', 'History']),
    );

    expect(find.text('Pick your dates'), findsNothing);
    // The other slots answer with chips instead.
    expect(find.text('Food'), findsOneWidget);
    expect(find.text('History'), findsOneWidget);
  });

  testWidgets('no affordance at all once the intake is done', (tester) async {
    // current_field is null outside the collecting step.
    await pumpChat(tester, _AskingRepository(null));

    expect(find.text('Pick your dates'), findsNothing);
    expect(find.byIcon(Icons.calendar_month_rounded), findsNothing);
  });
}
