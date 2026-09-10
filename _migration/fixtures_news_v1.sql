-- v1 fixture data for the news migration gate.
-- Covers: enriched + unenriched + duplicate articles, an article with no source
-- name, every interaction table, an over-cap dwell, and a taste dimension that
-- has no destination in app_new.
INSERT INTO roles(id,name) VALUES (1,'trader') ON CONFLICT DO NOTHING;

INSERT INTO users(id,country_code,phone_number,is_active,created_at) VALUES
 ('11111111-1111-1111-1111-111111111111','+91','9000000001',true,now()),
 ('22222222-2222-2222-2222-222222222222','+91','9000000002',true,now());

INSERT INTO profile(id,users_id,role_id,name,quantity_min,quantity_max,
                    is_user_verified,is_business_verified,followers_count,following_count,created_at,updated_at)
VALUES (1,'11111111-1111-1111-1111-111111111111',1,'Alice',0,100,false,false,0,0,now(),now()),
       (2,'22222222-2222-2222-2222-222222222222',1,'Bob',0,100,false,false,0,0,now(),now());

INSERT INTO news_raw_articles
 (id,external_id,title,description,content,article_url,image_url,published_at,
  source_name,source_url,is_duplicate,api_summary,intelligence_status,platform_arrived_at,is_active,created_at,updated_at)
VALUES
 ('aaaaaaaa-0000-0000-0000-000000000001','x1','Govt bans rice exports','Policy move','body','http://n/1','http://i/1.png',
  now()-interval '3 hours','Reuters','https://reuters.com/x',false,'api sum','enriched',now()-interval '3 hours',true,now(),now()),
 ('aaaaaaaa-0000-0000-0000-000000000002','x2','Brazil drought hits soy',NULL,'body2','http://n/2',NULL,
  now()-interval '2 days','PTI','https://ptinews.com/y',false,'prov summary','enriched',now()-interval '2 days',true,now(),now()),
 ('aaaaaaaa-0000-0000-0000-000000000003','x3','Unenriched filler',NULL,NULL,'http://n/3',NULL,
  now()-interval '1 day',NULL,NULL,false,NULL,'pending',now()-interval '1 day',false,now(),now()),
 ('aaaaaaaa-0000-0000-0000-000000000004','x4','A duplicate',NULL,NULL,'http://n/4',NULL,
  now(),'Reuters','https://reuters.com/z',true,NULL,'enriched',now(),true,now(),now());

INSERT INTO news_enriched_articles
 (id,raw_article_id,primary_factor,factor_scores,geo_category,is_government,commodity_tags,state_tags,
  summary_bullets,impact_direction,impact_score,impact_explanation,role_trader,role_broker,role_exporter,generated_at,created_at)
VALUES
 (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000001','policy_regulation','[]','domestic',true,
  '["rice"]','["MH"]','["India bans exports.","Traders disrupted."]','negative',8.5,'Export ban bites',9,9,9,now(),now()),
 (gen_random_uuid(),'aaaaaaaa-0000-0000-0000-000000000002','supply_disruptions','[]','global',false,
  '["soybean"]','[]','["Drought cuts output."]','positive',7.0,'Supply shortfall',8,8,8,now(),now());

INSERT INTO news_likes(profile_id,article_id,created_at)
VALUES (1,'aaaaaaaa-0000-0000-0000-000000000001',now());
INSERT INTO news_saves(profile_id,article_id,created_at)
VALUES (1,'aaaaaaaa-0000-0000-0000-000000000002',now());
INSERT INTO news_shares(profile_id,article_id,platform,created_at)
VALUES (2,'aaaaaaaa-0000-0000-0000-000000000001','whatsapp',now());
INSERT INTO news_views(profile_id,article_id,first_viewed_at,last_viewed_at,view_count)
VALUES (2,'aaaaaaaa-0000-0000-0000-000000000002',now(),now(),3);

-- 900000ms exceeds app_old's 600000ms cap and must be clamped on the way over
INSERT INTO news_interaction_events(profile_id,article_id,event_type,value_ms,occurred_at,created_at) VALUES
 (1,'aaaaaaaa-0000-0000-0000-000000000001','dwell',900000,now(),now()),
 (1,'aaaaaaaa-0000-0000-0000-000000000001','open_article',NULL,now(),now());

INSERT INTO news_raw_trending(article_id,velocity_score,trending_rank,computed_at)
VALUES ('aaaaaaaa-0000-0000-0000-000000000001',42.5,1,now());

-- only the 'factor' dimension has a destination in app_new; 'commodity' must be dropped
INSERT INTO user_news_taste(profile_id,dimension_type,dimension_key,positive_score,negative_score,event_count,last_event_at)
VALUES (1,'factor','policy_regulation',8.0,1.0,12,now()),
       (1,'commodity','rice',5.0,0.0,4,now());
