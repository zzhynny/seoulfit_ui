import '../../models/chat.dart';
import '../repositories/chat_repository.dart';

class MockChatRepository implements ChatRepository {
  @override
  Future<List<ChatMessage>> fetchConversation() async {
    await Future.delayed(const Duration(milliseconds: 150));
    return const [
      ChatMessage(
        sender: ChatSender.bot,
        text:
            "Annyeong! I'm your SeoulFit. When are you planning to visit beautiful Seoul, and for how long?",
      ),
      ChatMessage(
        sender: ChatSender.user,
        text: 'I will be visiting from October 12th for about 5 days.',
      ),
      ChatMessage(
        sender: ChatSender.bot,
        text:
            'Perfect! October is gorgeous with autumn foliage. Who are you traveling with? It helps me customize the pace.',
        showTravelerSelector: true,
        readyToBuild: true,
      ),
    ];
  }

  @override
  Future<ChatMessage> sendMessage(String text) async {
    await Future.delayed(const Duration(milliseconds: 400));
    return const ChatMessage(
      sender: ChatSender.bot,
      text:
          "Got it! I'm putting together a few options — head to the Trip tab once you're ready to see your itinerary.",
    );
  }

  @override
  List<OnTripHelpTopic> onTripTopics() => kOnTripTopics;
}
