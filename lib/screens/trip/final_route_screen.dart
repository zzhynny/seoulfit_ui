import 'package:flutter/material.dart';
import '../../models/trip.dart';
import '../../theme/theme.dart';

class FinalRouteScreen extends StatefulWidget {
  const FinalRouteScreen({
    super.key,
    required this.itinerary,
    required this.onResetItinerary,
    required this.onBack,
  });

  final Itinerary itinerary;
  final VoidCallback onResetItinerary;
  final VoidCallback onBack;

  @override
  State<FinalRouteScreen> createState() => _FinalRouteScreenState();
}

class _FinalRouteScreenState extends State<FinalRouteScreen> {
  bool _showTransitTip = true;

  @override
  Widget build(BuildContext context) {
    final stops = widget.itinerary.routeStops;
    return Column(
      children: [
        Padding(
          padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
          child: Row(
            crossAxisAlignment: CrossAxisAlignment.center,
            children: [
              GestureDetector(
                onTap: widget.onBack,
                child: const Padding(
                  padding: EdgeInsets.only(right: 4),
                  child: Icon(Icons.chevron_left, size: 24, color: Color(0xFF2D2A26)),
                ),
              ),
              Expanded(
                child: Column(
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.center,
                      children: [
                        Text('Your Route', style: AppTextStyles.headingMedium.copyWith(fontSize: 24, color: const Color(0xFF2D2A26))),
                        const SizedBox(width: 8),
                        Container(
                          padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                          decoration: BoxDecoration(
                            border: Border.all(color: const Color(0xFF5E836A)),
                            borderRadius: BorderRadius.circular(999),
                          ),
                          child: Text(
                            '${stops.length + 4} stops planned',
                            style: AppTextStyles.caption.copyWith(color: const Color(0xFF5E836A), fontWeight: FontWeight.w700),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 6),
                    Text(
                      'Curated walking & transit guidance for your day',
                      style: AppTextStyles.bodySmall.copyWith(color: const Color(0xFF8A857D)),
                    ),
                  ],
                ),
              ),
              const SizedBox(width: 24),
            ],
          ),
        ),
        Expanded(
          child: ListView(
            padding: const EdgeInsets.only(bottom: 8),
            children: [
              Padding(
                padding: const EdgeInsets.symmetric(horizontal: 16),
                child: ClipRRect(
                  borderRadius: BorderRadius.circular(18),
                  child: Container(
                    height: 200,
                    width: double.infinity,
                    decoration: BoxDecoration(
                      color: const Color(0xFFF3F5F4),
                      border: Border.all(color: AppColors.borderAlt),
                    ),
                    child: Image.asset('assets/images/final-route-map.png', fit: BoxFit.cover),
                  ),
                ),
              ),
              if (_showTransitTip)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 16, 16, 0),
                  child: Container(
                    padding: const EdgeInsets.fromLTRB(16, 10, 14, 10),
                    decoration: BoxDecoration(
                      color: const Color(0xFFFDFBF4),
                      border: Border.all(color: const Color(0xFFEFE8DB)),
                      borderRadius: BorderRadius.circular(16),
                    ),
                    child: Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text('💳 Paying for transit in Seoul',
                                  style: AppTextStyles.bodySmall.copyWith(fontWeight: FontWeight.w700, color: const Color(0xFF2D2A26))),
                              const SizedBox(height: 8),
                              _bullet('Tag your T-money or contactless card at readers'),
                              _bullet("Buses don't give change - use exact fare or card"),
                              _bullet('Single-journey tokens: refundable ₩500 deposit'),
                            ],
                          ),
                        ),
                        IconButton(
                          onPressed: () => setState(() => _showTransitTip = false),
                          icon: const Icon(Icons.close, size: 16),
                          padding: EdgeInsets.zero,
                          constraints: const BoxConstraints(),
                        ),
                      ],
                    ),
                  ),
                ),
              Padding(
                padding: const EdgeInsets.all(16),
                child: Column(
                  children: [
                    for (var i = 0; i < stops.length; i++) ...[
                      _PlaceStopCard(stop: stops[i], index: i + 1),
                      if (i < stops.length - 1) const _HopGuide(),
                    ],
                  ],
                ),
              ),
              GestureDetector(
                onTap: widget.onResetItinerary,
                child: Padding(
                  padding: const EdgeInsets.only(bottom: 16),
                  child: RichText(
                    textAlign: TextAlign.center,
                    text: TextSpan(
                      style: AppTextStyles.bodySmall.copyWith(color: const Color(0xFF888888)),
                      children: const [
                        TextSpan(text: 'Want to create a different plan? '),
                        TextSpan(
                          text: 'Reset itinerary',
                          style: TextStyle(decoration: TextDecoration.underline),
                        ),
                      ],
                    ),
                  ),
                ),
              ),
            ],
          ),
        ),
      ],
    );
  }

  Widget _bullet(String text) {
    return Padding(
      padding: const EdgeInsets.only(bottom: 4),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Padding(
            padding: const EdgeInsets.only(top: 6, right: 8),
            child: Container(width: 6, height: 6, decoration: const BoxDecoration(color: AppColors.primary, shape: BoxShape.circle)),
          ),
          Expanded(child: Text(text, style: AppTextStyles.caption.copyWith(fontSize: 11))),
        ],
      ),
    );
  }
}

class _PlaceStopCard extends StatelessWidget {
  const _PlaceStopCard({required this.stop, required this.index});

  final RouteStop stop;
  final int index;

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: Colors.white,
        border: Border.all(color: AppColors.borderAlt),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Row(
        children: [
          Container(
            width: 28,
            height: 28,
            decoration: const BoxDecoration(color: AppColors.primary, shape: BoxShape.circle),
            alignment: Alignment.center,
            child: Text('$index', style: AppTextStyles.caption.copyWith(color: Colors.white, fontWeight: FontWeight.w800)),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Expanded(
                      child: Text(
                        stop.nameKo != null ? '${stop.nameEn}\n${stop.nameKo}' : stop.nameEn,
                        style: AppTextStyles.headingSmall.copyWith(fontSize: 16, color: const Color(0xFF2D2A26)),
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(color: const Color(0xFFF4F0E8), borderRadius: BorderRadius.circular(10)),
                      child: Text(stop.arrivalTime, style: AppTextStyles.caption.copyWith(fontWeight: FontWeight.w700, color: const Color(0xFF2D2A26))),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                Row(
                  children: [
                    Text("📍 How do I know I'm here?", style: AppTextStyles.caption.copyWith(color: const Color(0xFF8A857D))),
                    const Icon(Icons.expand_more, size: 16, color: Color(0xFF8A857D)),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}

class _HopGuide extends StatelessWidget {
  const _HopGuide();

  @override
  Widget build(BuildContext context) {
    return Container(
      width: double.infinity,
      margin: const EdgeInsets.symmetric(vertical: 12),
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFFF3F5F4),
        border: Border.all(color: AppColors.borderAlt),
        borderRadius: BorderRadius.circular(16),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                height: 32,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                decoration: BoxDecoration(color: const Color(0xFF5E836A), borderRadius: BorderRadius.circular(10)),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.train, size: 16, color: Colors.white),
                    const SizedBox(width: 6),
                    Text('Subway (18m)', style: AppTextStyles.caption.copyWith(color: Colors.white, fontWeight: FontWeight.w700)),
                  ],
                ),
              ),
              const SizedBox(width: 8),
              Container(
                height: 32,
                padding: const EdgeInsets.symmetric(horizontal: 12),
                decoration: BoxDecoration(
                  color: Colors.white,
                  border: Border.all(color: AppColors.borderAlt),
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.directions_bus, size: 16, color: Color(0xFF66615B)),
                    const SizedBox(width: 6),
                    Text('Bus (21m)', style: AppTextStyles.caption.copyWith(color: const Color(0xFF66615B), fontWeight: FontWeight.w700)),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 12),
          Text('🚇 Subway Line 2 · 18 min · ₩1,400 · 420m walk',
              style: AppTextStyles.caption.copyWith(color: const Color(0xFF8A857D), fontWeight: FontWeight.w500)),
          const SizedBox(height: 12),
          Container(
            width: double.infinity,
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            decoration: BoxDecoration(color: const Color(0xFFEBF0EC), borderRadius: BorderRadius.circular(12)),
            child: Row(
              children: [
                const Icon(Icons.location_on_outlined, size: 16, color: Color(0xFF5E836A)),
                const SizedBox(width: 8),
                Text('Get off: Exit 9', style: AppTextStyles.caption.copyWith(color: const Color(0xFF5E836A), fontWeight: FontWeight.w700)),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
