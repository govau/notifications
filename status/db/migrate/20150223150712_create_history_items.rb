class CreateHistoryItems < ActiveRecord::Migration[4.2]
  def change
    create_table :history_items do |t|
      t.string :item_type
      t.integer :item_id
      t.datetime :date
    end
  end
end
