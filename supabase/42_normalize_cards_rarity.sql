-- Migration 42: normalize cards.rarity to canonical casing/spacing.
--
-- Lorcast publishes rarity as "Super_rare" (snake_case, underscore) and other
-- variants we sometimes get back. Every UI surface compares against the
-- canonical strings ("Super Rare", "Common", etc.) — the underscore form
-- silently fails the filter, so Super-Rare cards were missing from the
-- rare-leg movers banner and the Screener rarity filter.
--
-- The client also normalizes on read as a defensive guard, but fixing the
-- stored data is the right long-term answer (means the matview rows are
-- correct, exports are correct, any downstream tooling sees clean values).
--
-- Idempotent. Re-run safely.

update public.cards
   set rarity = case
     when lower(rarity) = 'super_rare' or lower(rarity) = 'super rare' then 'Super Rare'
     when lower(rarity) = 'common'                                     then 'Common'
     when lower(rarity) = 'uncommon'                                   then 'Uncommon'
     when lower(rarity) = 'rare'                                       then 'Rare'
     when lower(rarity) = 'legendary'                                  then 'Legendary'
     when lower(rarity) = 'enchanted'                                  then 'Enchanted'
     when lower(rarity) = 'epic'                                       then 'Epic'
     when lower(rarity) = 'iconic'                                     then 'Iconic'
     when lower(rarity) = 'promo'                                      then 'Promo'
     else rarity
   end
 where rarity is not null
   and rarity <> case
     when lower(rarity) = 'super_rare' or lower(rarity) = 'super rare' then 'Super Rare'
     when lower(rarity) = 'common'                                     then 'Common'
     when lower(rarity) = 'uncommon'                                   then 'Uncommon'
     when lower(rarity) = 'rare'                                       then 'Rare'
     when lower(rarity) = 'legendary'                                  then 'Legendary'
     when lower(rarity) = 'enchanted'                                  then 'Enchanted'
     when lower(rarity) = 'epic'                                       then 'Epic'
     when lower(rarity) = 'iconic'                                     then 'Iconic'
     when lower(rarity) = 'promo'                                      then 'Promo'
     else rarity
   end;

-- Refresh the matview so price_movers carries the new canonical values.
select public.refresh_price_movers();

-- Confirmation query (run separately if you want to sanity-check):
--   select rarity, count(*) from public.cards group by rarity order by rarity;
