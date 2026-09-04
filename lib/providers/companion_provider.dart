import 'package:flutter/foundation.dart';
import '../models/companion.dart';

/// Holds the user's currently-selected travel-buddy companion.
/// Every screen that shows the companion (chat avatar, loading screens,
/// profile, Trip empty-state, day-complete celebration) reads from this
/// provider instead of hardcoding an animal.
class CompanionProvider extends ChangeNotifier {
  CompanionProvider({CompanionId initial = CompanionId.tiger})
      : _selected = kCompanions[initial]!;

  Companion _selected;
  Companion get selected => _selected;

  String? _userName;
  String? get userName => _userName;

  void selectCompanion(CompanionId id) {
    _selected = kCompanions[id]!;
    notifyListeners();
  }

  void setUserName(String name) {
    _userName = name;
    notifyListeners();
  }
}
