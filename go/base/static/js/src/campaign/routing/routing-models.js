// go.campaign.routing (models)
// ============================
// Models for campaign routing screen.

// We use the state machine models as a base to make use of any
// custom/overriden functionality the models provide over Backbone.Model,
// seeing as the models for campaign routing are of a state machine nature.
var stateMachine = go.components.stateMachine,
    EndpointModel = stateMachine.EndpointModel,
    ConnectionModel = stateMachine.ConnectionModel,
    StateModel = stateMachine.StateModel,
    StateMachineModel = stateMachine.StateMachineModel;

(function(exports) {
  var RoutingEndpointModel = EndpointModel.extend({
    idAttribute: 'uuid'
  });

  var RoutingEntryModel = ConnectionModel.extend({
    idAttribute: 'uuid'
  });

  var ChannelModel = StateModel.extend({
    idAttribute: 'uuid',

    relations: [{
      type: Backbone.HasMany,
      key: 'endpoints',
      relatedModel: EndpointModel
    }]
  });

  var RoutingBlockModel = StateModel.extend({
    idAttribute: 'uuid',

    relations: [{
      type: Backbone.HasMany,
      key: 'conversation_endpoints',
      relatedModel: EndpointModel
    }, {
      type: Backbone.HasMany,
      key: 'channel_endpoints',
      relatedModel: EndpointModel
    }]
  });

  var ConversationModel = StateModel.extend({
    idAttribute: 'uuid',

    relations: [{
      type: Backbone.HasMany,
      key: 'endpoints',
      relatedModel: EndpointModel
    }]
  });

  var CampaignRoutingModel = StateMachineModel.extend({
    idAttribute: 'campaign_id',

    relations: [{
      type: Backbone.HasMany,
      key: 'channels',
      relatedModel: ChannelModel
    }, {
      type: Backbone.HasMany,
      key: 'routing_blocks',
      relatedModel: RoutingBlockModel
    }, {
      type: Backbone.HasMany,
      key: 'conversations',
      relatedModel: ConversationModel
    }, {
      type: Backbone.HasMany,
      key: 'routing_entries',
      relatedModel: RoutingEntryModel
    }]
  });

  _.extend(exports, {
    CampaignRoutingModel: CampaignRoutingModel,

    ChannelModel: ChannelModel,
    RoutingBlockModel: RoutingBlockModel,
    ConversationModel: ConversationModel,

    RoutingEntryModel: RoutingEntryModel,
    RoutingEndpointModel: RoutingEndpointModel
  });
})(go.campaign.routing);
