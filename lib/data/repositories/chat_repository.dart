import '../../models/chat.dart';

abstract class ChatRepository {
  Future<List<ChatMessage>> fetchConversation();
  Future<ChatMessage> sendMessage(String text);
  List<OnTripHelpTopic> onTripTopics();
}
