import '../../models/chat.dart';
import '../../models/travel_state.dart';
import '../../services/api_service.dart';
import '../repositories/chat_repository.dart';

/// [ChatRepository] backed by the FastAPI planner's conversational intake.
///
/// Shares its [ApiService] — and so its `thread_id` — with
/// [ApiTripRepository]: this conversation *is* how the itinerary gets built,
/// so the two must read and write the same LangGraph thread.
class ApiChatRepository implements ChatRepository {
  ApiChatRepository(this._api);

  final ApiService _api;

  /// Opens the conversation. `null` asks the backend for its greeting rather
  /// than sending a turn.
  ///
  /// The backend keeps history server-side in the LangGraph checkpoint and
  /// exposes only the latest AI message, so there is no transcript to
  /// restore — a returning user sees one bubble, not their scrollback.
  @override
  Future<List<ChatMessage>> fetchConversation() async {
    return [_botMessage(await _api.chat(null))];
  }

  @override
  Future<ChatMessage> sendMessage(String text) async {
    return _botMessage(await _api.chat(text));
  }

  @override
  List<OnTripHelpTopic> onTripTopics() => kOnTripTopics;

  ChatMessage _botMessage(TravelState state) {
    return ChatMessage(
      sender: ChatSender.bot,
      text: state.reply ?? '',
      // `confirm` is the step where the graph has every slot it needs and is
      // waiting on a yes — exactly when the "Build My Itinerary" CTA should
      // appear. Pressing it lands on Confirm Slots, which reads the same
      // state back via GET /state.
      readyToBuild: state.currentStep == 'confirm',
    );
  }
}
